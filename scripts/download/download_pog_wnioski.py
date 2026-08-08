#!/usr/bin/env python3
"""Download and extract source PDFs for the public comments register."""

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath


INDEX_URL = "https://bip.um.wroc.pl/artykuly/1309/1/25/uwagi"
ARCHIVE_HOST = "vip2.lo.pl"
ARCHIVE_PATH_RE = re.compile(
    r"^/uploads/files/PlanOgolny/(?P<start>\d+)_(?P<end>\d+)_ua\.zip$",
    re.IGNORECASE,
)
PDF_NAME_RE = re.compile(r"^(?P<number>\d+)_ua\.pdf$", re.IGNORECASE)
ARTICLE_PATH_RE = re.compile(r"^/artykul/1309/\d+/.+$")
USER_AGENT = "wroclaw-plan-ogolny-analiza/1.0"
CHUNK_SIZE = 1024 * 1024


class LinkCollector(HTMLParser):
    """Collect href attributes without requiring an HTML parser dependency."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if href:
            self.links.append(href)


@dataclass(frozen=True)
class ArchiveSource:
    article_url: str
    archive_url: str
    range_start: int
    range_end: int

    @property
    def filename(self):
        return Path(urllib.parse.urlsplit(self.archive_url).path).name

    @property
    def expected_ids(self):
        return range(self.range_start, self.range_end + 1)


class RequestError(RuntimeError):
    def __init__(self, message, code, metadata=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.metadata = metadata or {}
        self.retryable = retryable


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def response_metadata(response):
    headers = response.headers
    content_length = headers.get("Content-Length")
    try:
        content_length = int(content_length) if content_length else None
    except ValueError:
        content_length = None

    return {
        "http_status": response.getcode(),
        "final_url": response.geturl(),
        "content_type": headers.get_content_type(),
        "content_length": content_length,
        "last_modified": headers.get("Last-Modified"),
        "etag": headers.get("ETag"),
    }


def error_metadata(error):
    headers = getattr(error, "headers", None)
    content_type = None
    content_length = None
    if headers is not None:
        content_type = headers.get_content_type()
        raw_length = headers.get("Content-Length")
        try:
            content_length = int(raw_length) if raw_length else None
        except ValueError:
            content_length = None

    return {
        "http_status": getattr(error, "code", None),
        "final_url": error.geturl(),
        "content_type": content_type,
        "content_length": content_length,
    }


def retry_delay(base_delay, attempt):
    return base_delay * (2 ** (attempt - 1))


def fetch_page(url, timeout, retries, retry_base_delay):
    """Fetch an HTML page, retrying only transient failures."""
    last_error = None
    for attempt in range(1, retries + 2):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                metadata = response_metadata(response)
                if not 200 <= metadata["http_status"] < 300:
                    raise RequestError(
                        f"HTTP {metadata['http_status']} for {url}",
                        "http_error",
                        metadata,
                        metadata["http_status"] == 429
                        or metadata["http_status"] >= 500,
                    )
                return response.read(), metadata
        except urllib.error.HTTPError as error:
            metadata = error_metadata(error)
            retryable = error.code == 429 or error.code >= 500
            last_error = RequestError(
                f"HTTP {error.code} for {url}: {error.reason}",
                "http_error",
                metadata,
                retryable,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = RequestError(
                f"Request failed for {url}: {error}",
                "request_error",
                {"final_url": url},
                True,
            )

        if not last_error.retryable or attempt > retries:
            raise last_error
        time.sleep(retry_delay(retry_base_delay, attempt))

    raise last_error


def get_links(html, base_url):
    parser = LinkCollector()
    parser.feed(html.decode("utf-8", errors="replace"))
    return [urllib.parse.urljoin(base_url, link) for link in parser.links]


def discover_sources(index_url, timeout, retries, request_delay, retry_base_delay):
    index_html, _ = fetch_page(index_url, timeout, retries, retry_base_delay)
    index_links = get_links(index_html, index_url)

    article_urls = []
    seen_articles = set()
    for url in index_links:
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc != urllib.parse.urlsplit(index_url).netloc:
            continue
        if not ARTICLE_PATH_RE.fullmatch(parsed.path):
            continue
        article_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, "", "")
        )
        if article_url not in seen_articles:
            seen_articles.add(article_url)
            article_urls.append(article_url)

    sources = []
    seen_archives = set()
    for position, article_url in enumerate(article_urls, start=1):
        article_html, _ = fetch_page(
            article_url, timeout, retries, retry_base_delay
        )
        for url in get_links(article_html, article_url):
            parsed = urllib.parse.urlsplit(url)
            if parsed.netloc != ARCHIVE_HOST:
                continue
            match = ARCHIVE_PATH_RE.fullmatch(parsed.path)
            if not match:
                continue
            archive_url = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, "", "")
            )
            if archive_url in seen_archives:
                continue
            range_start = int(match.group("start"))
            range_end = int(match.group("end"))
            if range_start > range_end:
                raise RuntimeError(f"Invalid archive range in {archive_url}")
            seen_archives.add(archive_url)
            sources.append(
                ArchiveSource(
                    article_url=article_url,
                    archive_url=archive_url,
                    range_start=range_start,
                    range_end=range_end,
                )
            )
        if request_delay and position < len(article_urls):
            time.sleep(request_delay)

    sources.sort(key=lambda source: (source.range_start, source.range_end))
    return sources


def download_archive(source, temporary_dir, timeout, retries, retry_base_delay):
    """Download and validate one archive, returning its path and metadata."""
    archive_path = temporary_dir / source.filename
    last_error = None

    for attempt in range(1, retries + 2):
        try:
            if archive_path.exists():
                archive_path.unlink()

            request = urllib.request.Request(
                source.archive_url,
                headers={"User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                metadata = response_metadata(response)
                if not 200 <= metadata["http_status"] < 300:
                    raise RequestError(
                        f"HTTP {metadata['http_status']} for {source.archive_url}",
                        "http_error",
                        metadata,
                        metadata["http_status"] == 429
                        or metadata["http_status"] >= 500,
                    )

                digest = hashlib.sha256()
                bytes_downloaded = 0
                with archive_path.open("wb") as output:
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        bytes_downloaded += len(chunk)

            expected_size = metadata.get("content_length")
            if expected_size is not None and expected_size != bytes_downloaded:
                raise RequestError(
                    f"Expected {expected_size} bytes, downloaded {bytes_downloaded}",
                    "incomplete_download",
                    metadata,
                    True,
                )

            if not zipfile.is_zipfile(archive_path):
                raise RequestError(
                    "Response is not a ZIP archive",
                    "not_zip",
                    metadata,
                    False,
                )

            with zipfile.ZipFile(archive_path) as archive:
                corrupt_entry = archive.testzip()
            if corrupt_entry is not None:
                raise RequestError(
                    f"Corrupt ZIP entry: {corrupt_entry}",
                    "corrupt_zip",
                    metadata,
                    False,
                )

            metadata.update(
                {
                    "bytes_downloaded": bytes_downloaded,
                    "sha256": digest.hexdigest(),
                }
            )
            return archive_path, metadata
        except urllib.error.HTTPError as error:
            metadata = error_metadata(error)
            last_error = RequestError(
                f"HTTP {error.code} for {source.archive_url}: {error.reason}",
                "http_error",
                metadata,
                error.code == 429 or error.code >= 500,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = RequestError(
                f"Request failed for {source.archive_url}: {error}",
                "request_error",
                {"final_url": source.archive_url},
                True,
            )
        except RequestError as error:
            last_error = error

        if not last_error.retryable or attempt > retries:
            raise last_error
        time.sleep(retry_delay(retry_base_delay, attempt))

    raise last_error


def is_pdf(path):
    try:
        with path.open("rb") as input_file:
            return input_file.read(5) == b"%PDF-"
    except OSError:
        return False


def present_ids(source, output_dir):
    return {
        number
        for number in source.expected_ids
        if is_pdf(output_dir / f"{number}_ua.pdf")
    }


def extract_archive(archive_path, source, output_dir):
    """Extract expected PDFs while rejecting unsafe ZIP member paths."""
    expected_ids = set(source.expected_ids)
    extracted_ids = set()
    existing_ids = set()
    unexpected_entries = []
    duplicate_entries = []

    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue

            member_path = PurePosixPath(info.filename)
            if (
                member_path.is_absolute()
                or ".." in member_path.parts
                or len(member_path.parts) != 1
            ):
                unexpected_entries.append(info.filename)
                continue

            match = PDF_NAME_RE.fullmatch(member_path.name)
            if not match:
                unexpected_entries.append(info.filename)
                continue

            number = int(match.group("number"))
            if number not in expected_ids:
                unexpected_entries.append(info.filename)
                continue
            if number in extracted_ids or number in existing_ids:
                duplicate_entries.append(info.filename)
                continue

            final_path = output_dir / f"{number}_ua.pdf"
            if is_pdf(final_path):
                existing_ids.add(number)
                continue

            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{number}_ua.",
                    suffix=".part",
                    dir=output_dir,
                    delete=False,
                ) as output:
                    temporary_path = Path(output.name)
                    with archive.open(info) as input_file:
                        while True:
                            chunk = input_file.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            output.write(chunk)
                if not is_pdf(temporary_path):
                    raise RuntimeError(f"Extracted file is not a PDF: {info.filename}")
                os.replace(temporary_path, final_path)
                extracted_ids.add(number)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()

    all_present = existing_ids | extracted_ids
    missing_ids = sorted(expected_ids - all_present)
    return {
        "existing_pdf_ids": sorted(existing_ids),
        "extracted_pdf_ids": sorted(extracted_ids),
        "present_pdf_ids": sorted(all_present),
        "missing_pdf_ids": missing_ids,
        "unexpected_entries": sorted(unexpected_entries),
        "duplicate_entries": sorted(duplicate_entries),
    }


def base_record(source):
    return {
        "article_url": source.article_url,
        "archive_url": source.archive_url,
        "archive_filename": source.filename,
        "range_start": source.range_start,
        "range_end": source.range_end,
        "expected_pdf_count": source.range_end - source.range_start + 1,
    }


def record_with_status(source, status, present, error=None, metadata=None):
    expected = set(source.expected_ids)
    record = base_record(source)
    record.update(
        {
            "checked_at": utc_now(),
            "status": status,
            "present_pdf_ids": sorted(present),
            "missing_pdf_ids": sorted(expected - set(present)),
            "missing_pdf_count": len(expected - set(present)),
        }
    )
    if error is not None:
        record.update(
            {
                "error_code": error.code,
                "error": str(error),
            }
        )
    if metadata:
        record.update(metadata)
    return record


def process_archive(source, output_dir, timeout, retries, retry_base_delay):
    already_present = present_ids(source, output_dir)
    expected = set(source.expected_ids)
    if already_present == expected:
        return record_with_status(source, "already_present", already_present)

    try:
        with tempfile.TemporaryDirectory(prefix="pog-attachments-") as temp_dir:
            archive_path, metadata = download_archive(
                source,
                Path(temp_dir),
                timeout,
                retries,
                retry_base_delay,
            )
            extraction = extract_archive(archive_path, source, output_dir)
            present = set(extraction["present_pdf_ids"])
            status = "complete" if not extraction["missing_pdf_ids"] else "partial"
            record = record_with_status(source, status, present, metadata=metadata)
            record.update(
                {
                    "new_pdf_ids": extraction["extracted_pdf_ids"],
                    "unexpected_entries": extraction["unexpected_entries"],
                    "duplicate_entries": extraction["duplicate_entries"],
                }
            )
            return record
    except RequestError as error:
        return record_with_status(
            source,
            "unavailable",
            already_present,
            error=error,
            metadata=error.metadata,
        )
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        return record_with_status(
            source,
            "extraction_error",
            present_ids(source, output_dir),
            error=RequestError(str(error), "extraction_error"),
        )


def load_manifest(path):
    if not path.exists():
        return {}
    records = {}
    with path.open(encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"Invalid JSONL at {path}:{line_number}") from error
            archive_url = record.get("archive_url")
            if archive_url:
                records[archive_url] = record
    return records


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".part",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            output.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_manifest(path, records):
    ordered = sorted(
        records.values(),
        key=lambda record: (
            record.get("range_start", 0),
            record.get("range_end", 0),
            record.get("archive_url", ""),
        ),
    )
    content = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in ordered
    )
    atomic_write(path, content)


def build_summary(sources, records, started_at):
    current = [records[source.archive_url] for source in sources if source.archive_url in records]
    statuses = Counter(record.get("status") for record in current)
    expected_pdf_count = sum(record.get("expected_pdf_count", 0) for record in current)
    missing_pdf_count = sum(record.get("missing_pdf_count", 0) for record in current)
    present_pdf_count = expected_pdf_count - missing_pdf_count
    return {
        "started_at": started_at,
        "updated_at": utc_now(),
        "archive_count": len(sources),
        "processed_archive_count": len(current),
        "status_counts": dict(sorted(statuses.items())),
        "expected_pdf_count": expected_pdf_count,
        "present_pdf_count": present_pdf_count,
        "missing_pdf_count": missing_pdf_count,
        "missing_archive_count": sum(
            1 for record in current if record.get("status") == "unavailable"
        ),
    }


def write_summary(path, summary):
    atomic_write(path, json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Pobiera i rozpakowuje PDF-y z załączników do wykazu uwag."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/wnioski"),
        help="katalog docelowy PDF-ów (domyślnie: data/raw/wnioski)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="ARCHIVE",
        help="przetwórz tylko podane nazwy ZIP-ów; opcję można powtarzać",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="maksymalna liczba archiwów do przetworzenia",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="wykryj i wypisz źródła bez pobierania archiwów",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.retries < 0 or args.limit == 0:
        raise SystemExit("--retries musi być >= 0, a --limit nie może być równe 0")

    sources = discover_sources(
        INDEX_URL,
        args.timeout,
        args.retries,
        args.delay,
        args.retry_delay,
    )
    if args.only:
        wanted = set(args.only)
        sources = [source for source in sources if source.filename in wanted]
        missing_filters = wanted - {source.filename for source in sources}
        if missing_filters:
            raise SystemExit(
                "Nie znaleziono archiwów: " + ", ".join(sorted(missing_filters))
            )
    if args.limit is not None:
        sources = sources[: args.limit]
    if not sources:
        raise SystemExit("Brak archiwów do przetworzenia")

    print(f"Znaleziono archiwów: {len(sources)}")
    if args.dry_run:
        for source in sources:
            print(
                f"{source.filename}: {source.range_start}-{source.range_end} "
                f"({source.article_url})"
            )
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "pog_uwagi_attachments_manifest.jsonl"
    summary_path = args.output_dir / "pog_uwagi_attachments_summary.json"
    records = load_manifest(manifest_path)
    started_at = utc_now()

    for position, source in enumerate(sources, start=1):
        print(f"[{position}/{len(sources)}] {source.filename}")
        record = process_archive(
            source,
            args.output_dir,
            args.timeout,
            args.retries,
            args.retry_delay,
        )
        records[source.archive_url] = record
        write_manifest(manifest_path, records)
        summary = build_summary(sources, records, started_at)
        write_summary(summary_path, summary)
        print(
            f"  status={record['status']} "
            f"obecnych={len(record['present_pdf_ids'])} "
            f"brakujących={record['missing_pdf_count']}"
        )
        if args.delay:
            time.sleep(args.delay)

    summary = build_summary(sources, records, started_at)
    print(
        f"Podsumowanie: PDF-y obecne {summary['present_pdf_count']}/"
        f"{summary['expected_pdf_count']}, "
        f"brakujące {summary['missing_pdf_count']}"
    )
    return 1 if summary["missing_pdf_count"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RequestError as error:
        raise SystemExit(f"Błąd: {error}")
