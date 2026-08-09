# Materiały źródłowe pobrane z BIP

## Raport z konsultacji społecznych

- Plik: `pog_raport_z_konsultacji_spol.pdf`
- Źródło: https://bip.um.wroc.pl/artykul/1174/91089/raport-z-konsultacji-spolecznych
- Link bezpośredni: https://bip.um.wroc.pl/attachments/download/178331

## Wykaz uwag zgłoszonych do projektu planu ogólnego miasta Wrocławia

- Plik: `pog_wykaz_uwag_.pdf`
- Źródło: https://bip.um.wroc.pl/artykul/1174/91089/raport-z-konsultacji-spolecznych
- Link bezpośredni: https://bip.um.wroc.pl/attachments/download/178314

## Protokół ze zbierania uwag

- Plik: `pog_protokol_uwagi.pdf`
- Źródło: https://bip.um.wroc.pl/artykul/1174/91089/raport-z-konsultacji-spolecznych
- Link bezpośredni: https://bip.um.wroc.pl/attachments/download/178330

## Protokół z geoankiety

- Plik: `pog_protokol_geoankieta.pdf`
- Źródło: https://bip.um.wroc.pl/artykul/1174/91089/raport-z-konsultacji-spolecznych
- Link bezpośredni: https://bip.um.wroc.pl/attachments/download/178325

# Dane przestrzenne z ArcGIS REST

Dane pobrano 2026.08.08 skryptem `scripts/download/download_arcgis.py` z serwera REST Urzędu Miejskiego Wrocławia:

- Endpoint usług: https://gis.um.wroc.pl/portal_srv/rest/services
- Format danych: GeoJSON w natywnym układzie współrzędnych EPSG:2177 (ETRF2000-PL / CS2000, strefa 6)
- Pobrano wszystkie rekordy z każdej warstwy z użyciem paginacji po maksymalnie 2000 rekordów

### Osiedla Wrocławia

- Plik: `arcgis/osiedla_wroclawia.geojson`
- Warstwa: https://gis.um.wroc.pl/portal_srv/rest/services/Osiedla_Wroc%C5%82awia/MapServer/0

### Uwagi do projektu planu ogólnego

- Plik: `arcgis/pog_uwagi.geojson`
- Warstwa: https://gis.um.wroc.pl/portal_srv/rest/services/POG_PROJEKT_OBOW_uwagi/MapServer/15

### Liczba uwag do projektu planu ogólnego

- Plik: `arcgis/pog_liczba_uwag.geojson`
- Warstwa: https://gis.um.wroc.pl/portal_srv/rest/services/POG_PROJEKT_OBOW_uwagi/MapServer/16

### Strefy planistyczne w projekcie poddanym pod głosowanie

- Plik: `arcgis/pog_obow_strefy_planistyczne.geojson`
- Warstwa: https://gis.um.wroc.pl/portal_srv/rest/services/POG_PROJEKT_OBOW_strefy_planistyczne/MapServer/7

### Strefy planistyczne w projekcie poddanym pod konsultacje społeczne

- Plik: `arcgis/pog_ks_strefy_planistyczne.geojson`
- Warstwa: https://gis.um.wroc.pl/portal_srv/rest/services/POG_PROJEKT_KS_strefy_planistyczne/MapServer/7

# Źródłowe treści wniosków

Załączniki do wykazu uwag są pobierane i rozpakowywane skryptem:

```bash
python3 scripts/download/download_pog_uwagi.py
```

Skrypt pobiera listę archiwów z podstron BIP, a następnie zapisuje rozpakowane
pliki PDF w `data/raw/wnioski/`, np. `data/raw/wnioski/5651_ua.pdf`. Archiwa
ZIP są przechowywane wyłącznie tymczasowo poza repozytorium.

Stan pobierania jest zapisywany w:

- `data/raw/wnioski/pog_uwagi_attachments_manifest.jsonl` - status każdego archiwum, źródła,
  zakresy numerów, hash i listy brakujących PDF-ów,
- `data/raw/wnioski/pog_uwagi_attachments_summary.json` - zbiorcze liczniki pobranych i
  brakujących plików.

Skrypt jest idempotentny: poprawne, już istniejące PDF-y są pomijane, a
nieudostępnione lub niepełne zakresy są ponawiane przy kolejnym uruchomieniu.
