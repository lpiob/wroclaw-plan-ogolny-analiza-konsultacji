#!/usr/bin/env python3
"""Split the source area description into semicolon-separated references."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/processed/pog_wykaz_uwag.jsonl")
DEFAULT_OUTPUT = Path("data/processed/pog_uwagi_obszary.jsonl")

ATTACHMENT_REFERENCE = re.compile(
    r"\bzałącznik\w*(?:\s+graficzn\w+)?\s+nr\.?\s*(\d+)\b",
    re.IGNORECASE,
)


def read_records(input_path: Path) -> Iterator[dict[str, Any]]:
    """Read source records and report malformed JSONL with its line number."""

    if not input_path.is_file():
        raise FileNotFoundError(f"Nie znaleziono pliku wejściowego: {input_path}")

    with input_path.open(encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Nieprawidłowy JSON w wierszu {line_number}: {error}"
                ) from error

            if not isinstance(record, dict):
                raise ValueError(
                    f"Wiersz {line_number} nie zawiera obiektu JSON."
                )

            yield record


def attachment_index(notice_number: object, fragment: str) -> str | None:
    """Return a notice-scoped reference for a single attachment mention."""

    attachment_numbers = ATTACHMENT_REFERENCE.findall(fragment)
    if len(attachment_numbers) != 1:
        return None

    return (
        f"zalacznik|uwaga={notice_number}|nr={attachment_numbers[0]}"
    )


def extracted_records(
    records: Iterable[dict[str, Any]],
) -> tuple[Iterator[dict[str, Any]], dict[str, str]]:
    """Yield one record per area fragment and build the global reference map."""

    area_indexes: dict[str, str] = {}
    next_area_number = 1

    def generate() -> Iterator[dict[str, Any]]:
        nonlocal next_area_number

        for record in records:
            try:
                area_raw = record["obszar_raw"]
                notice_number = record["oznaczenie_uwagi"]
                data_wplywu = record["data_wplywu"]
                pdf_page = record["pdf_page"]
            except KeyError as error:
                raise ValueError(
                    f"Brak wymaganego pola w uwadze: {error.args[0]}"
                ) from error

            if not isinstance(area_raw, str):
                raise ValueError(
                    f"Pole obszar_raw w uwadze {notice_number} nie jest tekstem."
                )

            fragments = [fragment.strip() for fragment in area_raw.split(";")]
            fragments = [fragment for fragment in fragments if fragment]

            for order, fragment in enumerate(fragments, start=1):
                reference = attachment_index(notice_number, fragment)
                if reference is None:
                    reference = area_indexes.get(fragment)
                    if reference is None:
                        reference = f"obszar-{next_area_number:06d}"
                        area_indexes[fragment] = reference
                        next_area_number += 1

                yield {
                    "data_wplywu": data_wplywu,
                    "oznaczenie_uwagi": notice_number,
                    "kolejnosc": order,
                    "obszar_extracted_raw": fragment,
                    "obszar_unique_index": reference,
                    "pdf_page": pdf_page,
                }

    return generate(), area_indexes


def write_jsonl(records: Iterable[dict[str, Any]], output_path: Path) -> int:
    """Write records atomically so a failed conversion preserves the output."""

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
        ) as output_file:
            temporary_path = Path(output_file.name)
            for record in records:
                json.dump(record, output_file, ensure_ascii=False)
                output_file.write("\n")
                count += 1

        temporary_path.replace(output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return count


def convert(input_path: Path, output_path: Path) -> tuple[int, int]:
    records, area_indexes = extracted_records(read_records(input_path))
    record_count = write_jsonl(records, output_path)
    return record_count, len(area_indexes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rozdziela pole obszar_raw na fragmenty oddzielone średnikami."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"plik źródłowy JSONL (domyślnie: {DEFAULT_INPUT})",
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
    record_count, area_count = convert(args.input, args.output)
    print(
        f"Zapisano {record_count} rekordów i {area_count} unikalnych obszarów "
        f"do {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
