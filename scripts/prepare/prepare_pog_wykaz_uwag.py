#!/usr/bin/env python3
"""Extract the comments table from the source PDF into JSON Lines."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

import pymupdf


DEFAULT_INPUT = Path("data/raw/pog_wykaz_uwag_.pdf")
DEFAULT_OUTPUT = Path("data/processed/pog_wykaz_uwag.jsonl")

# The PDF is rotated. PyMuPDF returns the original coordinate system, where
# the table columns are separated by the second word coordinate (y0).
# These boundaries are stable in the source PDF, unlike text-column offsets
# produced by pdftotext -layout.
LP_START = 1140.0
DATE_START = 1090.0
NOTICE_START = 1045.0
AREA_START = 768.0
DECISION_START = 690.0

LINE_TOLERANCE = 0.75
MAX_CONTINUATION_GAP = 30.0
ROW_START = re.compile(r"^\d+$")
DATE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")


@dataclass
class PdfLine:
    axis: float
    words: list[tuple]


@dataclass
class Record:
    date_raw: str
    notice_number: int
    page_start: int
    area_parts: list[str] = field(default_factory=list)
    decision_parts: list[str] = field(default_factory=list)
    justification_parts: list[str] = field(default_factory=list)

    def add_columns(self, columns: dict[str, str]) -> None:
        if columns["area"]:
            self.area_parts.append(columns["area"])
        if columns["decision"]:
            self.decision_parts.append(columns["decision"])
        if columns["justification"]:
            self.justification_parts.append(columns["justification"])

    def to_dict(self) -> dict[str, object]:
        date = datetime.strptime(self.date_raw, "%d.%m.%Y").date().isoformat()
        return {
            "data_wplywu": date,
            "oznaczenie_uwagi": self.notice_number,
            "obszar_raw": " ".join(self.area_parts),
            "propozycja_rozpatrzenia": " ".join(self.decision_parts),
            "uzasadnienie": " ".join(self.justification_parts),
            "pdf_page": self.page_start,
        }


def classify_word(word: tuple) -> str | None:
    """Assign a word to a table column using its PDF coordinate."""

    column_axis = word[1]
    if column_axis >= LP_START:
        return "lp"
    if column_axis >= DATE_START:
        return "date"
    if column_axis >= NOTICE_START:
        return "notice"
    if column_axis >= AREA_START:
        return "area"
    if column_axis >= DECISION_START:
        return "decision"
    return "justification"


def group_page_words(page: pymupdf.Page) -> Iterator[PdfLine]:
    """Group words sharing a rendered text line."""

    words = sorted(
        page.get_text("words", sort=False),
        key=lambda word: (word[0], -word[1]),
    )
    current: PdfLine | None = None

    for word in words:
        line_axis = word[0]
        if current is None or abs(line_axis - current.axis) > LINE_TOLERANCE:
            if current is not None:
                yield current
            current = PdfLine(axis=line_axis, words=[word])
        else:
            current.words.append(word)

    if current is not None:
        yield current


def line_columns(line: PdfLine) -> dict[str, str]:
    words_by_column: defaultdict[str, list[tuple]] = defaultdict(list)
    for word in line.words:
        column = classify_word(word)
        if column is not None:
            words_by_column[column].append(word)

    columns = {column: "" for column in ("lp", "date", "notice")}
    columns.update(
        {column: "" for column in ("area", "decision", "justification")}
    )

    for column, words in words_by_column.items():
        # Rotation makes the natural reading direction descend along the
        # second coordinate.
        words.sort(key=lambda word: word[1], reverse=True)
        columns[column] = " ".join(word[4] for word in words)

    return columns


def parse_row_start(columns: dict[str, str]) -> tuple[str, int] | None:
    if not (
        ROW_START.fullmatch(columns["lp"])
        and DATE.fullmatch(columns["date"])
        and ROW_START.fullmatch(columns["notice"])
    ):
        return None

    return (
        columns["date"],
        int(columns["notice"]),
    )


def parse_records(pdf_path: Path) -> Iterator[dict[str, object]]:
    """Yield one dictionary for each logical row in the PDF table."""

    document = pymupdf.open(str(pdf_path))
    current: Record | None = None
    last_line_axis: float | None = None
    last_page_number: int | None = None
    table_ended_on_page = False

    try:
        for page_number, page in enumerate(document, start=1):
            if page_number != last_page_number:
                last_line_axis = None
                last_page_number = page_number
                table_ended_on_page = False

            for line in group_page_words(page):
                columns = line_columns(line)
                row_start = parse_row_start(columns)

                if row_start is not None:
                    if current is not None:
                        yield current.to_dict()

                    date_raw, notice_number = row_start
                    current = Record(
                        date_raw=date_raw,
                        notice_number=notice_number,
                        page_start=page_number,
                    )
                    current.add_columns(columns)
                    last_line_axis = line.axis
                    table_ended_on_page = False
                    continue

                if current is None or table_ended_on_page:
                    continue

                if (
                    last_line_axis is not None
                    and line.axis - last_line_axis > MAX_CONTINUATION_GAP
                ):
                    # This excludes page numbers, the annex and the
                    # electronic signature after the final table row.
                    table_ended_on_page = True
                    continue

                has_table_content = any(
                    columns[column]
                    for column in ("area", "decision", "justification")
                )
                if has_table_content:
                    current.add_columns(columns)
                    last_line_axis = line.axis

        if current is not None:
            yield current.to_dict()
    finally:
        document.close()


def write_jsonl(records: Iterable[dict[str, object]], output_path: Path) -> int:
    """Write records atomically so a failed extraction does not replace output."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    count = 0

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            for record in records:
                json.dump(record, temporary_file, ensure_ascii=False)
                temporary_file.write("\n")
                count += 1

        if count == 0:
            raise RuntimeError("Nie znaleziono żadnych rekordów w pliku PDF.")

        temporary_path.replace(output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return count


def convert(input_path: Path, output_path: Path) -> int:
    if not input_path.is_file():
        raise FileNotFoundError(f"Nie znaleziono pliku wejściowego: {input_path}")

    return write_jsonl(parse_records(input_path), output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Przekształca wykaz uwag z PDF do JSON Lines."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"plik źródłowy PDF (domyślnie: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"plik wynikowy JSONL (domyślnie: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    count = convert(args.input, args.output)
    print(f"Zapisano {count} rekordów do {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
