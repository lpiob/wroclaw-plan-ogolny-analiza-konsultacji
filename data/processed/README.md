# Pliki

- `pog_wykaz_uwag.jsonl` przetworzony 1:1 plik `../raw/pog_wykaz_uwag_.pdf` bez modyfikacji. Plik ten grupuje uwagi, tj. jeśli jeden wniosek miał kilka uwag, to niestety są umieszczane w jednym wierszu. Realizacja za pomocą `scripts/prepare/prepare_pog_wykaz_uwag.py`.
- `pog_wnioski_page_headers.jsonl` plik utworzony z skanów wniosków (`../raw/wnioski/*`) za pomocą OCR i skryptu `scripts/prepare/prepare_pog_page_headers.py`. Zawiera nagłówki każdej strony każdego wniosku.
- `pog_uwagi_obszary.jsonl` plik utworzony z powyższego poprzez porzucenie sposobu rozpatrzenia wniosków oraz rozdzielenie wniosków na uwagi - każda w osobnym wierszu. Wykorzystano skrypt `scripts/prepare/prepare_pog_uwagi_obszary.py` który dodatkowo uzupełnia uwagi o lokalizację geograficzną.

## Sposób użycia

OCR wniosków:

```
python3 scripts/prepare/prepare_pog_page_headers.py \
  --input-dir data/raw/wnioski \
  --output data/processed/pog_wnioski_page_headers.jsonl \
  --workers 8 \
  --resume  # jeśli ma wznowić pracę, np. przetworzyć wnioski których brakowało
  ```
