#!/usr/bin/env python3
"""Return planning-zone centroids as EPSG:2177 coordinates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, TextIO


DEFAULT_GEOJSON = Path("data/raw/arcgis/pog_ks_strefy_planistyczne.geojson")
FALLBACK_GEOJSON = Path("data/raw/arcgis/pog_obow_strefy_planistyczne.geojson")
COORDINATE_DECIMALS = 1
ZONE_REFERENCE = re.compile(
    r"\bstrefa\s+(?P<designation>\d+[A-Za-z]+)\b", re.IGNORECASE
)
COUNTED_LINE = re.compile(r"^\s*\d+\s+(?P<value>.+?)\s*$")


def parse_zone_line(line: str, line_number: int) -> str | None:
    """Parse a JSON string or a line produced by ``uniq -c``."""

    value = line.strip()
    if not value:
        return None

    counted_line = COUNTED_LINE.fullmatch(value)
    if counted_line is not None:
        value = counted_line.group("value")

    try:
        parsed_value: Any = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value

    if not isinstance(parsed_value, str):
        raise ValueError(
            f"Wiersz {line_number} nie zawiera nazwy strefy jako tekstu."
        )

    match = ZONE_REFERENCE.search(parsed_value.strip())
    if match is None:
        raise ValueError(
            f"Nie znaleziono kodu strefy w wierszu {line_number}: {parsed_value!r}"
        )

    return match.group("designation").upper()


def read_requested_zones(input_file: TextIO) -> list[str]:
    """Read unique zone designations from stdin while preserving input order."""

    requested: dict[str, None] = {}
    for line_number, line in enumerate(input_file, start=1):
        designation = parse_zone_line(line, line_number)
        if designation is not None:
            requested.setdefault(designation, None)
    return list(requested)


def ring_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    """Return a ring's centroid and doubled signed area."""

    if len(ring) < 3:
        raise ValueError("Pierścień poligonu musi zawierać co najmniej 3 punkty.")

    points = list(ring)
    if points[0] != points[-1]:
        points.append(points[0])

    area2 = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    for first, second in zip(points, points[1:]):
        cross = first[0] * second[1] - second[0] * first[1]
        area2 += cross
        centroid_x += (first[0] + second[0]) * cross
        centroid_y += (first[1] + second[1]) * cross

    if abs(area2) <= 1e-12:
        raise ValueError("Nie można wyznaczyć środka zdegenerowanego poligonu.")

    return centroid_x / (3.0 * area2), centroid_y / (3.0 * area2), area2


def polygon_centroid(rings: list[list[list[float]]]) -> tuple[float, float]:
    """Return the area-weighted centroid of a polygon, including its holes."""

    total_area2 = 0.0
    total_centroid_x = 0.0
    total_centroid_y = 0.0

    for ring in rings:
        centroid_x, centroid_y, area2 = ring_centroid(ring)
        total_area2 += area2
        total_centroid_x += centroid_x * area2
        total_centroid_y += centroid_y * area2

    if abs(total_area2) <= 1e-12:
        raise ValueError("Nie można wyznaczyć środka poligonu.")

    return (
        total_centroid_x / total_area2,
        total_centroid_y / total_area2,
    )


def feature_centroid(feature: dict[str, Any]) -> tuple[float, float]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise ValueError("Oczekiwano geometrii typu Polygon.")

    rings = geometry.get("coordinates")
    if not isinstance(rings, list) or not rings:
        raise ValueError("Poligon nie zawiera współrzędnych.")

    return polygon_centroid(rings)


def read_zone_centers(geojson_path: Path) -> dict[str, tuple[float, float]]:
    """Read all zone centroids from the source GeoJSON."""

    with geojson_path.open(encoding="utf-8") as input_file:
        data = json.load(input_file)

    if not isinstance(data, dict):
        raise ValueError("Główny obiekt GeoJSON nie jest obiektem JSON.")

    crs_name = data.get("crs", {}).get("properties", {}).get("name")
    if crs_name != "EPSG:2177":
        raise ValueError(
            f"Nieoczekiwany układ współrzędnych GeoJSON: {crs_name!r}; "
            "oczekiwano EPSG:2177."
        )

    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError("GeoJSON nie zawiera listy obiektów features.")

    centers: dict[str, tuple[float, float]] = {}
    for feature in features:
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("Obiekt GeoJSON nie zawiera właściwości properties.")

        designation = properties.get("OZNACZENIE")
        if not isinstance(designation, str):
            raise ValueError("Obiekt GeoJSON nie zawiera tekstowego OZNACZENIE.")

        designation = designation.upper()
        if designation in centers:
            raise ValueError(f"Powtórzone oznaczenie strefy: {designation}.")

        centers[designation] = feature_centroid(feature)

    return centers


def write_output(
    requested: list[str], centers: dict[str, tuple[float, float]]
) -> None:
    """Write the requested centers in the project's inferred-coordinates format."""

    print("{")
    for index, designation in enumerate(requested):
        x, y = centers[designation]
        coordinates = [
            round(x, COORDINATE_DECIMALS),
            round(y, COORDINATE_DECIMALS),
        ]
        comma = "," if index < len(requested) - 1 else ""
        key = json.dumps(f"strefa {designation}", ensure_ascii=False)
        value = json.dumps(coordinates, ensure_ascii=False)
        print(f"    {key}: {{")
        print(f'        "inferred_coordinates": {value}')
        print(f"    }}{comma}")
    print("}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Zwraca środki stref planistycznych na podstawie nazw "
            "odczytanych ze standardowego wejścia."
        )
    )
    parser.add_argument(
        "geojson",
        nargs="?",
        type=Path,
        default=DEFAULT_GEOJSON,
        help=(
            f"główny plik GeoJSON (domyślnie: {DEFAULT_GEOJSON}); "
            f"brakujące strefy są szukane w {FALLBACK_GEOJSON}"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        requested = read_requested_zones(sys.stdin)
        centers = read_zone_centers(args.geojson)
        missing = [designation for designation in requested if designation not in centers]
        if missing:
            fallback_centers = read_zone_centers(FALLBACK_GEOJSON)
            still_missing = []
            for designation in missing:
                fallback_center = fallback_centers.get(designation)
                if fallback_center is None:
                    still_missing.append(designation)
                else:
                    centers[designation] = fallback_center

            if still_missing:
                names = ", ".join(
                    f"strefa {designation}" for designation in still_missing
                )
                raise ValueError(
                    f"Nie znaleziono stref w plikach GeoJSON: {names}."
                )
        write_output(requested, centers)
    except (OSError, ValueError) as error:
        print(f"Błąd: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
