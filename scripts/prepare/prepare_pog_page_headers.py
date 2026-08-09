#!/usr/bin/env python3
"""OCR the top part of every page in source application PDFs.

The output contains one JSON object per input PDF.  Only the rendered page
header is passed to Tesseract; the rest of each scanned page is never OCR'd.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import pymupdf


DEFAULT_INPUT_DIR = Path("data/raw/wnioski")
DEFAULT_OUTPUT = Path("data/processed/pog_wnioski_page_headers.jsonl")
DEFAULT_DPI = 300
DEFAULT_LANGUAGE = "pol"
DEFAULT_PSM = 6
DEFAULT_TOP_FRACTION = 0.1
DEFAULT_WORKERS = min(8, os.cpu_count() or 1)
PDF_NAME_RE = re.compile(r"^(?P<wniosek>\d+)_ua\.pdf$", re.IGNORECASE)


def parse_wniosek_number(pdf_path: Path) -> int:
    """Return the application number encoded in a source PDF filename."""

    match = PDF_NAME_RE.fullmatch(pdf_path.name)
    if match is None:
        raise ValueError(
            f"Nazwa pliku nie pasuje do wzorca <wniosek>_ua.pdf: {pdf_path}"
        )
    return int(match.group("wniosek"))


def normalize_ocr_text(text: str) -> str:
    """Remove OCR wrapper whitespace while preserving line breaks."""

    lines = [line.strip() for line in text.replace("\r\n", "\n").splitlines()]
    return "\n".join(line for line in lines if line)


def render_page_header(
    page: pymupdf.Page,
    dpi: int,
    top_fraction: float,
) -> pymupdf.Pixmap:
    """Render the visible top fraction of a page after applying its rotation."""

    page_rect = page.rect
    clip = pymupdf.Rect(
        page_rect.x0,
        page_rect.y0,
        page_rect.x1,
        page_rect.y0 + page_rect.height * top_fraction,
    )
    return page.get_pixmap(
        dpi=dpi,
        colorspace=pymupdf.csGRAY,
        alpha=False,
        clip=clip,
    )


def run_tesseract(
    image: pymupdf.Pixmap,
    *,
    dpi: int,
    language: str,
    psm: int,
    executable: str,
) -> str:
    """Run Tesseract on a rendered header supplied through stdin."""

    command = [
        executable,
        "stdin",
        "stdout",
        "--dpi",
        str(dpi),
        "--psm",
        str(psm),
        "-l",
        language,
    ]
    result = subprocess.run(
        command,
        input=image.tobytes("png"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            # One Tesseract process per worker is already parallelized.
            "OMP_NUM_THREADS": "1",
            "OMP_THREAD_LIMIT": "1",
        },
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Tesseract zakończył się kodem {result.returncode}: {error}"
        )
    return normalize_ocr_text(result.stdout.decode("utf-8", errors="replace"))


def base_record(pdf_path: Path) -> dict[str, object]:
    return {
        "file": str(pdf_path),
        "wniosek": parse_wniosek_number(pdf_path),
        "page_count": 0,
        "status": "ok",
        "page_headers": {},
    }


def process_pdf(
    pdf_path: Path,
    *,
    dpi: int = DEFAULT_DPI,
    language: str = DEFAULT_LANGUAGE,
    psm: int = DEFAULT_PSM,
    top_fraction: float = DEFAULT_TOP_FRACTION,
    tesseract: str = "tesseract",
    save_images: Path | None = None,
) -> dict[str, object]:
    """OCR page headers from one PDF and return a JSON-serializable record."""

    record = base_record(pdf_path)
    page_headers: dict[str, str] = {}
    page_errors: dict[str, str] = {}

    try:
        document = pymupdf.open(str(pdf_path))
    except Exception as error:
        record.update(
            {
                "status": "error",
                "error": f"Nie można otworzyć PDF-u: {error}",
                "page_headers": page_headers,
            }
        )
        return record

    try:
        record["page_count"] = len(document)
        for page_number, page in enumerate(document, start=1):
            page_key = str(page_number)
            try:
                image = render_page_header(page, dpi, top_fraction)
                if save_images is not None:
                    save_images.mkdir(parents=True, exist_ok=True)
                    image_path = save_images / (
                        f"{pdf_path.stem}_page-{page_number:03d}_header.png"
                    )
                    image.save(str(image_path))
                page_headers[page_key] = run_tesseract(
                    image,
                    dpi=dpi,
                    language=language,
                    psm=psm,
                    executable=tesseract,
                )
            except Exception as error:
                page_headers[page_key] = ""
                page_errors[page_key] = str(error)
    except Exception as error:
        record["status"] = "error"
        record["error"] = str(error)
    finally:
        document.close()

    record["page_headers"] = page_headers
    if page_errors:
        record["status"] = "error"
        record["page_errors"] = page_errors
    return record


def check_tesseract_language(executable: str, language: str) -> None:
    """Fail early when Tesseract or its requested language is unavailable."""

    if shutil.which(executable) is None:
        raise RuntimeError(f"Nie znaleziono programu Tesseract: {executable}")

    result = subprocess.run(
        [executable, "--list-langs"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    languages = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("List of available languages")
    }
    if language not in languages:
        raise RuntimeError(
            f"Tesseract nie ma modelu języka {language!r}. "
            f"Dostępne modele: {', '.join(sorted(languages))}"
        )


def pdf_paths(input_dir: Path) -> list[Path]:
    """Return source PDFs in deterministic application-number order."""

    paths = list(input_dir.glob("*_ua.pdf"))
    return sorted(paths, key=lambda path: (parse_wniosek_number(path), path.name))


def load_completed_files(output_path: Path) -> set[str]:
    """Read successfully written JSONL records for resumable processing."""

    completed: set[str] = set()
    with output_path.open(encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"Niepoprawny JSONL w {output_path}:{line_number}; "
                    "usuń uszkodzoną linię lub użyj --overwrite"
                ) from error
            file_name = record.get("file")
            if isinstance(file_name, str):
                completed.add(file_name)
    return completed


def write_jsonl(
    pdfs: Iterable[Path],
    output_path: Path,
    *,
    resume: bool,
    overwrite: bool,
    dpi: int,
    language: str,
    psm: int,
    top_fraction: float,
    tesseract: str,
    save_images: Path | None,
    workers: int,
) -> tuple[int, int]:
    """Process PDFs in parallel while writing JSONL from one thread."""

    if output_path.exists() and not resume and not overwrite:
        raise RuntimeError(
            f"Plik wynikowy już istnieje: {output_path}; użyj --resume albo --overwrite"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = load_completed_files(output_path) if resume and output_path.exists() else set()
    mode = "a" if resume and output_path.exists() else "w"
    skipped = 0
    pdf_list = list(pdfs)
    pending = []

    for pdf_path in pdf_list:
        if str(pdf_path) in completed:
            skipped += 1
        else:
            pending.append(pdf_path)

    for pdf_path in pdf_list:
        if str(pdf_path) in completed:
            print(f"pomijam {pdf_path.name}", file=sys.stderr)

    def process_one(pdf_path: Path) -> dict[str, object]:
        try:
            return process_pdf(
                pdf_path,
                dpi=dpi,
                language=language,
                psm=psm,
                top_fraction=top_fraction,
                tesseract=tesseract,
                save_images=save_images,
            )
        except Exception as error:
            record = base_record(pdf_path)
            record.update(
                {
                    "status": "error",
                    "error": f"Nieoczekiwany błąd workera: {error}",
                }
            )
            return record

    processed = 0

    with output_path.open(mode, encoding="utf-8", buffering=1) as output_file:
        if workers == 1:
            results = ((pdf_path, process_one(pdf_path)) for pdf_path in pending)
            for pdf_path, record in results:
                processed += 1
                print(f"OCR {pdf_path.name} ({processed}/{len(pending)})", file=sys.stderr)
                output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="pog-ocr",
            ) as executor:
                futures = {
                    executor.submit(process_one, pdf_path): pdf_path
                    for pdf_path in pending
                }
                for future in as_completed(futures):
                    pdf_path = futures[future]
                    record = future.result()
                    processed += 1
                    print(
                        f"OCR {pdf_path.name} ({processed}/{len(pending)})",
                        file=sys.stderr,
                    )
                    output_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return processed, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OCR-uje górny fragment każdej strony PDF-u i zapisuje JSONL."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        type=Path,
        help="pojedynczy PDF; bez tego argumentu przetwarzany jest katalog wejściowy",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"katalog PDF-ów (domyślnie: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=f"plik JSONL (domyślnie: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--psm", type=int, default=DEFAULT_PSM)
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=(
            "liczba równoległych PDF-ów w trybie katalogu "
            f"(domyślnie: {DEFAULT_WORKERS})"
        ),
    )
    parser.add_argument(
        "--top-fraction",
        type=float,
        default=DEFAULT_TOP_FRACTION,
        help="ułamek widocznej wysokości strony przekazywany do OCR",
    )
    parser.add_argument(
        "--save-images",
        type=Path,
        help="zapisuje przycięte obrazy przekazane do Tesseracta",
    )
    parser.add_argument("--tesseract", default="tesseract")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0 < args.top_fraction <= 1:
        raise SystemExit("--top-fraction musi być większe od 0 i nie większe niż 1")
    if args.dpi <= 0:
        raise SystemExit("--dpi musi być dodatnie")
    if args.workers <= 0:
        raise SystemExit("--workers musi być dodatnie")
    if args.pdf is not None and args.resume:
        raise SystemExit("--resume działa tylko w trybie katalogu")
    if args.resume and args.overwrite:
        raise SystemExit("--resume i --overwrite nie mogą być użyte jednocześnie")

    check_tesseract_language(args.tesseract, args.language)

    if args.pdf is not None:
        record = process_pdf(
            args.pdf,
            dpi=args.dpi,
            language=args.language,
            psm=args.psm,
            top_fraction=args.top_fraction,
            tesseract=args.tesseract,
            save_images=args.save_images,
        )
        serialized = json.dumps(record, ensure_ascii=False)
        if args.output is not None:
            if args.output.exists() and not args.overwrite:
                raise RuntimeError(
                    f"Plik wynikowy już istnieje: {args.output}; użyj --overwrite"
                )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as output_file:
                output_file.write(serialized + "\n")
        else:
            print(serialized)
        return 0 if record["status"] == "ok" else 1

    if not args.input_dir.is_dir():
        raise SystemExit(f"Nie znaleziono katalogu wejściowego: {args.input_dir}")
    paths = pdf_paths(args.input_dir)
    if not paths:
        raise SystemExit(f"Brak plików *_ua.pdf w katalogu: {args.input_dir}")

    output_path = args.output or DEFAULT_OUTPUT
    processed, skipped = write_jsonl(
        paths,
        output_path,
        resume=args.resume,
        overwrite=args.overwrite,
        dpi=args.dpi,
        language=args.language,
        psm=args.psm,
        top_fraction=args.top_fraction,
        tesseract=args.tesseract,
        save_images=args.save_images,
        workers=args.workers,
    )
    print(
        f"Zakończono: przetworzono {processed}, pominięto {skipped}; "
        f"wynik: {output_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as error:
        raise SystemExit(f"Błąd: {error}")
