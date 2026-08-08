#!/usr/bin/env python3
"""Download selected ArcGIS REST feature layers as GeoJSON snapshots."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PAGE_SIZE = 2000
NATIVE_CRS = 2177
REQUEST_DELAY_SECONDS = 0.05
REQUEST_TIMEOUT_SECONDS = 120

LAYERS = [
    (
        "osiedla_wroclawia",
        "Osiedla Wrocławia",
        "https://gis.um.wroc.pl/portal_srv/rest/services/Osiedla_Wroc%C5%82awia/MapServer/0",
    ),
    (
        "pog_uwagi",
        "Uwagi do projektu planu ogólnego",
        "https://gis.um.wroc.pl/portal_srv/rest/services/POG_PROJEKT_OBOW_uwagi/MapServer/15",
    ),
    (
        "pog_liczba_uwag",
        "Liczba uwag do projektu planu ogólnego",
        "https://gis.um.wroc.pl/portal_srv/rest/services/POG_PROJEKT_OBOW_uwagi/MapServer/16",
    ),
    (
        "pog_obow_strefy_planistyczne",
        "Strefy planistyczne w projekcie poddanym pod głosowanie",
        "https://gis.um.wroc.pl/portal_srv/rest/services/POG_PROJEKT_OBOW_strefy_planistyczne/MapServer/7",
    ),
    (
        "pog_ks_strefy_planistyczne",
        "Strefy planistyczne w projekcie poddanym pod konsultacje społeczne",
        "https://gis.um.wroc.pl/portal_srv/rest/services/POG_PROJEKT_KS_strefy_planistyczne/MapServer/7",
    ),
]


def get_json(url, params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "wroclaw-plan-ogolny-analiza/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ArcGIS HTTP {error.code} for {url}: {body}") from error

    if "error" in data:
        raise RuntimeError(f"ArcGIS error for {url}: {data['error']}")

    return data


def write_json(path, data, indent=2):
    with path.open("w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=indent)
        output.write("\n")


def get_oid_field(layer_metadata):
    for field in layer_metadata.get("fields", []):
        if field.get("type") == "esriFieldTypeOID":
            return field["name"]
    return "OBJECTID"


def download_layer(name, title, layer_url, output_dir):
    layer_metadata = get_json(layer_url, {"f": "pjson"})
    oid_field = get_oid_field(layer_metadata)
    features = []
    offset = 0
    crs = None

    while True:
        page = get_json(
            f"{layer_url}/query",
            {
                "f": "geojson",
                "where": "1=1",
                "outFields": "*",
                "outSR": NATIVE_CRS,
                "orderByFields": f"{oid_field} ASC",
                "resultOffset": offset,
                "resultRecordCount": PAGE_SIZE,
            },
        )
        if crs is None:
            crs = page.get("crs")
        batch = page.get("features", [])
        features.extend(batch)

        if not page.get("exceededTransferLimit", False) or not batch:
            break

        offset += len(batch)
        time.sleep(REQUEST_DELAY_SECONDS)

    output = {
        "type": "FeatureCollection",
        "crs": crs,
        "features": features,
    }
    write_json(output_dir / f"{name}.geojson", output, indent=None)
    return len(features)


def main():
    output_dir = Path("data/raw/arcgis")
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, title, layer_url in LAYERS:
        print(f"Pobieranie: {title}")
        records = download_layer(name, title, layer_url, output_dir)
        print(f"  rekordów: {records}")


if __name__ == "__main__":
    main()
