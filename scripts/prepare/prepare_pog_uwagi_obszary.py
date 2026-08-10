#!/usr/bin/env python3
"""Split area descriptions and resolve attachment locations from OCR headers."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/processed/pog_wykaz_uwag.jsonl")
DEFAULT_OUTPUT = Path("data/processed/pog_uwagi_obszary.jsonl")
DEFAULT_GIS_INPUT = Path("data/raw/arcgis/pog_uwagi.geojson")
DEFAULT_PAGE_HEADERS_INPUT = Path(
    "data/processed/pog_wnioski_page_headers.jsonl"
)

# Coordinates use GeoJSON [x, y] order in EPSG:2177.
KNOWN_LOCATIONS: dict[str, dict[str, object]] = {
    "Trasa Czeska wg archiwalnego Studium 2010": {
        "inferred_coordinates": [6426531.7, 5662217.0],
        "inferred_details": "Trasa Czeska",
    },
    "Osiedle Oporów": {
        "inferred_coordinates": [6427001.4, 5660944.5],
        "inferred_details": "Osiedle Oporów",
    },
    (
        "dz. 17/2 AR. 40 ob. Grabiszyn, dz. 17/6 AR. 40 ob. Grabiszyn, "
        "dz. 17/8 AR. 40 ob. Grabiszyn, dz. 19 AR. 40 ob. Grabiszyn, "
        "dz. 4 AR. 41 ob. Grabiszyn, dz. 2/8 AR. 1 ob. Krzyki, "
        "dz. 3/1 AR. 1 ob. Krzyki, dz. 5/1 AR. 1 ob. Krzyki, "
        "dz. 6/1 AR. 1 ob. Krzyki, dz. 10 AR. 42 ob. Grabiszyn, "
        "dz. 7/19 AR. 1 ob. Krzyki, dz. 7/2 AR. 37 ob. Grabiszyn, "
        "dz. 7/18 AR. 1 ob. Krzyki, dz. 1/3 AR. 2 ob. Krzyki, "
        "dz. 67 AR. 45 ob. Grabiszyn, dz. 1/3 AR. 6 ob. Borek"
    ): {
        "inferred_coordinates": [6429367.9, 5660953.9],
        "inferred_details": "Tramwaj na Racławickiej",
    },
    "dz. 2/8, 3/1, 3/2, 4/1, 5/1, 9/16, 9/17, 9/19, 9/21 AR.18 ob. Klecina, dz. 1, 2, 4/1, 10/5 AR.19 ob. Klecina, dz. 1/3, 1/4, 1/6, 1/9, 1/10, 2/14, 2/15, 2/16, 2/17, 3/3, 3/7, 4/1, 14/3 AR.1 ob. Krzyki, dz. 46/1, 47/1, 48/1 AR.4 ob. Krzyki, dz. 1/1, 2/1, 3/1, 5/2, 6/4, 6/19, 7/1, 7/2, 7/3 AR.9 ob. Krzyki": {
        "inferred_coordinates": [6428940.9, 5660337.1],
        "inferred_details": "Zachowanie Parku Krzyckiego",
    },
    "tereny 1KD-Z w obowiązujących miejscowych planach zagospodarowania przestrzennego zachodniej części obszaru rozwoju KRZYKI I we Wrocławiu (uchwała nr XVI/474/07 Rady Miejskiej Wrocławia z dnia 25 lutego 2008 r.) oraz południowej części obszaru rozwoju Krzyki I we Wrocławiu (uchwała nr XIV/339/07 Rady Miejskiej Wrocławia z dnia 27 stycznia 2008 r.)": {
        "inferred_coordinates": [6428940.9, 5660337.1],
        "inferred_details": "Zachowanie Parku Krzyckiego",
    },
    "zgodnie z załącznikiem graficznym nr 4 do uwagi, strefy 413SW, 394SW, 333SW, 318SW, 280SW, 45SN": {
        "inferred_coordinates": [6430095.5, 5659593.1],
        "inferred_details": "Zachowanie skali zabudowy na Krzykach i Partynicach",
    },
    "zgodnie z załącznikiem graficznym nr 3 do uwagi, strefy 413SW, 394SW, 333SW, 318SW, 280SW, 45SN": {
        "inferred_coordinates": [6430095.5, 5659593.1],
        "inferred_details": "Zachowanie skali zabudowy na Krzykach i Partynicach",
    },
    "zgodnie z załącznikiem graficznym nr 5 do uwagi, strefy 413SW, 394SW, 333SW, 318SW, 280SW, 45SN": {
        "inferred_coordinates": [6430095.5, 5659593.1],
        "inferred_details": "Zachowanie skali zabudowy na Krzykach i Partynicach",
    },
    "zgodnie z załącznikiem graficznym nr 2 do uwagi, strefy 413SW, 394SW, 333SW, 318SW, 280SW, 45SN": {
        "inferred_coordinates": [6430095.5, 5659593.1],
        "inferred_details": "Zachowanie skali zabudowy na Krzykach i Partynicach",
    },
    "dz. 67 AR. 45 ob. Grabiszyn, dz. 2 AR. 6 ob. Borek, dz. 1/2 AR. 45 ob. Grabiszyn, dz. 3/1 AR. 37 ob. Grabiszyn": {
        "inferred_coordinates": [6429887.53, 5661163.46],
        "inferred_details": "Węzeł przesiadkowy koło górki Skarbowców",
    },
    "dz. 7/39 AR. 23 ob. Grabiszyn, dz. 2/32 AR. 24 ob. Grabiszyn, dz. 25/2 AR. 27 ob. Grabiszyn, dz. 32/2 AR. 26 ob. Grabiszyn, dz. 18/5 AR. 23 ob. Grabiszyn, dz. 21/6, AR. 23 ob. Grabiszyn": {
        "inferred_coordinates": [6428547.4, 5662729.6],
        "inferred_details": "Uporządkowanie obszarów wokoł FAT",
    },
    "zgodnie z załącznikiem graficznym nr 3 do uwagi (strefa OUZ Krzyki-Partynice)": {
        "inferred_coordinates": [ 6430806.8, 5659695.2],
        "inferred_details": "Zachowanie kształtu osiedla Alina",
    },
    "zgodnie z załącznikiem graficznym nr 4 do uwagi (strefa OUZ Krzyki-Partynice)": {
        "inferred_coordinates": [ 6430806.8, 5659695.2],
        "inferred_details": "Zachowanie kształtu osiedla Alina",
    },
    "zgodnie z załącznikiem graficznym nr 3 do uwagi (strefa OUZ Krzyki- Partynice)": {
        "inferred_coordinates": [ 6430806.8, 5659695.2],
        "inferred_details": "Zachowanie kształtu osiedla Alina",
    },
    "strefa 100SN": {
        "inferred_coordinates": [6425556.0, 5668312.3]
    },
    "strefa 105SN": {
        "inferred_coordinates": [6429838.3, 5668938.3]
    },
    "strefa 1098SW": {
        "inferred_coordinates": [6436214.3, 5666560.0]
    },
    "strefa 125SO": {
        "inferred_coordinates": [6429404.0, 5673024.7]
    },
    "strefa 12SU": {
        "inferred_coordinates": [6435518.8, 5659155.5]
    },
    "strefa 133SI": {
        "inferred_coordinates": [6435791.8, 5667768.2]
    },
    "strefa 1493SW": {
        "inferred_coordinates": [6437459.3, 5668211.1]
    },
    "strefa 153SP": {
        "inferred_coordinates": [6421197.1, 5666890.5]
    },
    "strefa 1698SW": {
        "inferred_coordinates": [6438832.8, 5670034.1]
    },
    "strefa 1699SW": {
        "inferred_coordinates": [6438657.5, 5669988.6]
    },
    "strefa 16SP": {
        "inferred_coordinates": [6436474.5, 5659226.3]
    },
    "strefa 171SN": {
        "inferred_coordinates": [6434970.6, 5658809.9]
    },
    "strefa 1823SW": {
        "inferred_coordinates": [6433571.8, 5661640.4]
    },
    "strefa 1833SW": {
        "inferred_coordinates": [6433409.2, 5661787.8]
    },
    "strefa 1862SJ": {
        "inferred_coordinates": [6438849.5, 5664679.5]
    },
    "strefa 189SU": {
        "inferred_coordinates": [6429531.9, 5659885.2]
    },
    "strefa 1904SW": {
        "inferred_coordinates": [6429891.5, 5661956.4]
    },
    "strefa 2005SW": {
        "inferred_coordinates": [6431110.0, 5662509.2]
    },
    "strefa 2112SW": {
        "inferred_coordinates": [6432881.7, 5663013.0]
    },
    "strefa 2165SW": {
        "inferred_coordinates": [6429919.2, 5663211.4]
    },
    "strefa 2166SW": {
        "inferred_coordinates": [6432882.7, 5663210.4]
    },
    "strefa 225SN": {
        "inferred_coordinates": [6428531.6, 5660283.3]
    },
    "strefa 234SW": {
        "inferred_coordinates": [6435646.8, 5659075.3]
    },
    "strefa 2429SW": {
        "inferred_coordinates": [6431805.2, 5664259.0]
    },
    "strefa 2448SW": {
        "inferred_coordinates": [6431119.7, 5664311.4]
    },
    "strefa 2486SW": {
        "inferred_coordinates": [6432159.7, 5664221.4]
    },
    "strefa 2653SW": {
        "inferred_coordinates": [6434391.7, 5664832.9]
    },
    "strefa 2732SW": {
        "inferred_coordinates": [6431109.7, 5665018.0]
    },
    "strefa 2749SW": {
        "inferred_coordinates": [6433976.3, 5665092.5]
    },
    "strefa 2750SW": {
        "inferred_coordinates": [6430517.5, 5665052.3]
    },
    "strefa 286SW": {
        "inferred_coordinates": [6435327.6, 5659341.1]
    },
    "strefa 2893SW": {
        "inferred_coordinates": [6431149.5, 5665487.0]
    },
    "strefa 2894SW": {
        "inferred_coordinates": [6431035.5, 5665555.1]
    },
    "strefa 2897SW": {
        "inferred_coordinates": [6430945.0, 5665627.5]
    },
    "strefa 2901SW": {
        "inferred_coordinates": [6431140.0, 5665632.8]
    },
    "strefa 2909SW": {
        "inferred_coordinates": [6431006.7, 5665668.0]
    },
    "strefa 2914SW": {
        "inferred_coordinates": [6431098.1, 5665717.7]
    },
    "strefa 2915SW": {
        "inferred_coordinates": [6430942.5, 5665711.6]
    },
    "strefa 2926SW": {
        "inferred_coordinates": [6431052.5, 5665774.2]
    },
    "strefa 2949SW": {
        "inferred_coordinates": [6433313.6, 5665509.2]
    },
    "strefa 29SU": {
        "inferred_coordinates": [6431954.6, 5660302.4]
    },
    "strefa 3038SW": {
        "inferred_coordinates": [6428239.2, 5666049.9]
    },
    "strefa 3088SW": {
        "inferred_coordinates": [6428827.6, 5666243.5]
    },
    "strefa 3103SW": {
        "inferred_coordinates": [6429402.8, 5666434.6]
    },
    "strefa 3133SW": {
        "inferred_coordinates": [6432479.6, 5666966.7]
    },
    "strefa 3138SW": {
        "inferred_coordinates": [6432415.7, 5667120.7]
    },
    "strefa 3154SW": {
        "inferred_coordinates": [6427714.9, 5667376.2]
    },
    "strefa 3157SW": {
        "inferred_coordinates": [6432343.5, 5667361.9]
    },
    "strefa 3164SW": {
        "inferred_coordinates": [6432352.8, 5667320.9]
    },
    "strefa 3176SW": {
        "inferred_coordinates": [6431895.1, 5667514.8]
    },
    "strefa 3182SW": {
        "inferred_coordinates": [6432285.5, 5667521.0]
    },
    "strefa 3184SW": {
        "inferred_coordinates": [6432262.3, 5667584.2]
    },
    "strefa 3267SW": {
        "inferred_coordinates": [6433622.1, 5658720.4]
    },
    "strefa 3365SW": {
        "inferred_coordinates": [6424919.1, 5667602.4]
    },
    "strefa 3366SW": {
        "inferred_coordinates": [6424871.2, 5667531.3]
    },
    "strefa 3410SW": {
        "inferred_coordinates": [6430415.9, 5671874.9]
    },
    "strefa 3437SW": {
        "inferred_coordinates": [6431161.3, 5665726.9]
    },
    "strefa 3762SJ": {
        "inferred_coordinates": [6438722.6, 5670165.2]
    },
    "strefa 383SU": {
        "inferred_coordinates": [6438852.9, 5664724.4]
    },
    "strefa 4091SJ": {
        "inferred_coordinates": [6429460.8, 5672026.8]
    },
    "strefa 4095SJ": {
        "inferred_coordinates": [6430568.1, 5672253.5]
    },
    "strefa 4130SJ": {
        "inferred_coordinates": [6428813.6, 5673537.7]
    },
    "strefa 48SI": {
        "inferred_coordinates": [6421807.0, 5668861.4]
    },
    "strefa 530SU": {
        "inferred_coordinates": [6432328.9, 5667037.5]
    },
    "strefa 576SU": {
        "inferred_coordinates": [6439142.9, 5668067.9]
    },
    "strefa 585SU": {
        "inferred_coordinates": [6436059.5, 5668147.4]
    },
    "strefa 591SN": {
        "inferred_coordinates": [6436851.7, 5666859.1]
    },
    "strefa 623SW": {
        "inferred_coordinates": [6430373.2, 5661559.9]
    },
    "strefa 63SK": {
        "inferred_coordinates": [6427986.0, 5663820.2]
    },
    "strefa 649SU": {
        "inferred_coordinates": [6430446.0, 5672258.5]
    },
    "strefa 658SU": {
        "inferred_coordinates": [6432466.3, 5667122.9]
    },
    "strefa 658SW": {
        "inferred_coordinates": [6430056.2, 5661709.7]
    },
    "strefa 68SN": {
        "inferred_coordinates": [6438104.9, 5663526.8]
    },
    "strefa 73SW": {
        "inferred_coordinates": [6426938.9, 5664414.9]
    },
    "strefa 7SJ": {
        "inferred_coordinates": [6433521.7, 5657306.1]
    },
    "strefa 814SJ": {
        "inferred_coordinates": [6429899.4, 5659953.9]
    },
    "strefa 841SJ": {
        "inferred_coordinates": [6427831.9, 5660043.9]
    },
    "strefa 86SI": {
        "inferred_coordinates": [6427612.8, 5663275.9]
    },
    "strefa 86SU": {
        "inferred_coordinates": [6438562.2, 5664557.3]
    },
    "strefa 884SJ": {
        "inferred_coordinates": [6428639.3, 5660016.7]
    },
    "strefa 88SU": {
        "inferred_coordinates": [6438282.0, 5664615.7]
    },
    "strefa 90SK": {
        "inferred_coordinates": [6432410.7, 5661932.4]
    },
    "strefa 90SU": {
        "inferred_coordinates": [6428672.1, 5664728.5]
    },
    "strefa 99SU": {
        "inferred_coordinates": [6426148.5, 5665364.7]
    },
    "strefa 101SU": {
        "inferred_coordinates": [6430528.4, 5665537.5]
    },
    "strefa 11SH": {
        "inferred_coordinates": [6428327.9, 5666215.7]
    },
    "strefa 194SN": {
        "inferred_coordinates": [6427965.7, 5659535.2]
    },
    "strefa 3051SW": {
        "inferred_coordinates": [6429104.3, 5666130.1]
    },
    "strefa 3098SW": {
        "inferred_coordinates": [6427817.4, 5666413.1]
    },
    "strefa 3102SW": {
        "inferred_coordinates": [6427733.4, 5666461.7]
    },
    "strefa 3104SW": {
        "inferred_coordinates": [6427619.7, 5666431.3]
    },
    "strefa 3144SW": {
        "inferred_coordinates": [6432691.3, 5667298.0]
    },
    "strefa 35SI": {
        "inferred_coordinates": [6431724.4, 5665897.0]
    },
    "strefa 3639SJ": {
        "inferred_coordinates": [6436561.3, 5669631.7]
    },
    "strefa 3726SJ": {
        "inferred_coordinates": [6423046.7, 5669925.1]
    },
    "strefa 59SO": {
        "inferred_coordinates": [6417432.1, 5668050.5]
    },
    "strefa 5SK": {
        "inferred_coordinates": [6434061.8, 5657471.7]
    },
    "strefa 61SI": {
        "inferred_coordinates": [6435774.4, 5659296.8]
    },
    "strefa 637SU": {
        "inferred_coordinates": [6430852.7, 5670933.9]
    },
    "strefa 722SJ": {
        "inferred_coordinates": [6428564.4, 5659601.3]
    },
    "strefa 788SN": {
        "inferred_coordinates": [6426813.8, 5663482.6]
    },
    "strefa 79SU": {
        "inferred_coordinates": [6426523.8, 5663905.3]
    },
    "strefa 826SW": {
        "inferred_coordinates": [6437933.0, 5663384.6]
    },
    "strefa 90SN": {
        "inferred_coordinates": [6427588.5, 5666153.5]
    },
    "strefa 142SN": {
        "inferred_coordinates": [6435537.4, 5658399.4]
    },
    "strefa 2744SW": {
        "inferred_coordinates": [6426718.9, 5664792.2]
    },
    "strefa 2937SW": {
        "inferred_coordinates": [6428112.0, 5665716.9]
    },
    "strefa 2SO": {
        "inferred_coordinates": [6440099.3, 5670806.9]
    },
    "strefa 3348SW": {
        "inferred_coordinates": [6426627.6, 5666952.2]
    },
    "strefa 4102SJ": {
        "inferred_coordinates": [6423852.0, 5671852.7]
    },
    "strefa 501SU": {
        "inferred_coordinates": [6427010.5, 5666111.0]
    },
    "strefa 52SO": {
        "inferred_coordinates": [6439927.8, 5667116.4]
    },
    "strefa 586SU": {
        "inferred_coordinates": [6426102.9, 5667977.8]
    },
    "strefa 608SU": {
        "inferred_coordinates": [6423639.3, 5669167.9]
    },
    "strefa 65SI": {
        "inferred_coordinates": [6431239.9, 5659735.3]
    },
    "strefa 82SP": {
        "inferred_coordinates": [6428119.1, 5664140.5]
    },
    "strefa 10SK": {
        "inferred_coordinates": [6435403.9, 5658398.3]
    },
    "strefa 112SN": {
        "inferred_coordinates": [6423420.6, 5670697.7]
    },
    "strefa 1329SW": {
        "inferred_coordinates": [6438342.2, 5667635.5]
    },
    "strefa 39SN": {
        "inferred_coordinates": [6435105.3, 5658268.0]
    },
    "strefa 597SU": {
        "inferred_coordinates": [6423884.6, 5668392.8]
    },
    "strefa 5SN": {
        "inferred_coordinates": [6427217.7, 5661193.2]
    },
    "strefa 7SP": {
        "inferred_coordinates": [6428545.2, 5658431.2]
    },
    "strefa 92SW": {
        "inferred_coordinates": [6418889.9, 5667747.4]
    },
    "strefa 13SP": {
        "inferred_coordinates": [6428626.4, 5658683.3]
    },
    "strefa 165SN": {
        "inferred_coordinates": [6427245.5, 5658752.9]
    },
    "strefa 2685SW": {
        "inferred_coordinates": [6433961.0, 5664846.9]
    },
    "strefa 646SU": {
        "inferred_coordinates": [6430279.3, 5671638.4]
    },
    "strefa 653SU": {
        "inferred_coordinates": [6423391.7, 5669258.7]
    },
    "strefa 1345SW": {
        "inferred_coordinates": [6437930.5, 5667735.3]
    },
    "strefa 1434SW": {
        "inferred_coordinates": [6438345.9, 5667981.1]
    },
    "strefa 36SW": {
        "inferred_coordinates": [6433080.3, 5661009.2]
    },
    "strefa 2843SJ": {
        "inferred_coordinates": [6438611.2, 5667435.2]
    },
    "strefa 650SN": {
        "inferred_coordinates": [6431777.2, 5668219.8]
    },
    "strefa 189SP": {
        "inferred_coordinates": [6436569.6, 5671274.2]
    },
    "strefa 235SW": {
        "inferred_coordinates": [6435229.7, 5658797.3]
    },
    "strefa 1390SW": {
        "inferred_coordinates": [6438379.1, 5667859.1]
    },
    "strefa 3328SW": {
        "inferred_coordinates": [6425944.5, 5663811.1]
    },
    "strefa 39SI": {
        "inferred_coordinates": [6423194.1, 5666107.3]
    },
    "strefa 2601SW": {
        "inferred_coordinates": [6426770.2, 5664772.6]
    },
    "strefa 3170SW": {
        "inferred_coordinates": [6432207.3, 5667454.8]
    }
}

ATTACHMENT_REFERENCE = re.compile(
    r"\bzałącznik\w*(?:\s+graficzn\w+)?\s+(?:nr\.?\s*)?(\d+)\b",
    re.IGNORECASE,
)
ATTACHMENT_HEADER = re.compile(
    r"\bzałącznik\s+(?:nr\.?\s*)?(?P<number>\d+)\s*[:\-]\s*"
    r"(?P<title>[^\r\n]+)",
    re.IGNORECASE,
)

# Szczegoly odnosnie lokalizacji na podstawie danych z nazw załączników.
# wykorzystywane do lokalizowania uwag które w podsumowaniu urzedu odnosza się tylko do 'Załącznika nr x'
# a we właściwym wniosku opisują konkretnie o co chodzi.
# koordynaty [x, y] EPSG:2177
ATTACHMENT_LOCATION_RULES: tuple[
    tuple[re.Pattern[str], dict[str, object]], ...
] = (
    (
        re.compile(
            r"Zachowanie\s+.*\s+osiedla\s+Alina",
            re.IGNORECASE,
        ),
        {
            "inferred_coordinates": [6430806.8, 5659695.2],
            "inferred_details": "Zachowanie kształtu osiedla Alina",
            "rule_id": "zachowanie-osiedla-alina",
        },
    ),
    (
        re.compile(
            r"Ziele.*parku.*grabiszy.*iego",
            re.IGNORECASE,
        ),
        {
            "inferred_coordinates": [6428637.54, 5661062.41],
            "inferred_details": "Zieleń w rejonie parku Grabiszyńskiego",
            "rule_id": "zieleń-park-grabiszynski",
        },
    ),
    (
        re.compile(
            r"Skala.*zabudowy.*Krzyki.*Partynice",
            re.IGNORECASE,
        ),
        {
            "inferred_coordinates": [6430095.5, 5659593.1],
            "inferred_details": "Zachowanie skali zabudowy na Krzykach i Partynicach",
            "rule_id": "skala-zabudowy-kp",
        },
    ),
    (
        re.compile(
            r"W.*przesiadkowy.*Skarbow",
            re.IGNORECASE,
        ),
        {
            "inferred_coordinates": [6429887.53, 5661163.46],
            "inferred_details": "Węzeł przesiadkowy koło górki Skarbowców",
            "rule_id": "wezel-przesiadkowy-gs",
        },
    ),
    (
        re.compile(
            r"Sp.*plan.*na.*FAT",
            re.IGNORECASE,
        ),
        {
            "inferred_coordinates": [6428547.4, 5662729.6],
            "inferred_details": "Uporządkowanie obszarów wokoł FAT",
            "rule_id": "spojny-plan-na-fat",
        },
    ),
)


def normalize_attachment_title(title: str) -> str:
    """Normalize OCR noise around an attachment title."""

    title = re.sub(r"\s+", " ", title)
    return title.strip(" \t|,;:-")


def read_attachment_headers(
    input_path: Path,
) -> dict[tuple[int, int], list[dict[str, object]]]:
    """Index attachment titles from the optional, incrementally built JSONL."""

    if not input_path.is_file():
        return {}

    attachment_headers: dict[tuple[int, int], list[dict[str, object]]] = {}

    with input_path.open(encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                # The OCR producer writes records incrementally. A truncated
                # final line is an in-progress record, not a fatal input error.
                if not line.endswith("\n"):
                    continue
                raise ValueError(
                    f"Nieprawidłowy JSON w nagłówkach w wierszu "
                    f"{line_number}: {error}"
                ) from error

            if not isinstance(record, dict):
                raise ValueError(
                    f"Wiersz {line_number} nagłówków nie zawiera obiektu JSON."
                )

            notice_number = record.get("wniosek")
            page_headers = record.get("page_headers")
            if not isinstance(notice_number, int) or not isinstance(
                page_headers, dict
            ):
                continue

            for page_key, page_header in page_headers.items():
                if not isinstance(page_header, str):
                    continue
                try:
                    page_number = int(page_key)
                except (TypeError, ValueError):
                    continue

                for match in ATTACHMENT_HEADER.finditer(page_header):
                    title = normalize_attachment_title(match.group("title"))
                    if not title:
                        continue

                    attachment_key = (
                        notice_number,
                        int(match.group("number")),
                    )
                    evidence = {
                        "page": page_number,
                        "title": title,
                    }
                    existing_evidence = attachment_headers.setdefault(
                        attachment_key,
                        [],
                    )
                    if evidence not in existing_evidence:
                        existing_evidence.append(evidence)

    return attachment_headers


def attachment_number(fragment: str) -> int | None:
    """Return the number from a single attachment reference."""

    numbers = ATTACHMENT_REFERENCE.findall(fragment)
    if len(numbers) != 1:
        return None
    return int(numbers[0])


def match_attachment_location(
    titles: list[dict[str, object]],
) -> tuple[dict[str, object] | None, list[str], str]:
    """Match attachment titles and reject conflicting location rules."""

    matched_locations: list[dict[str, object]] = []
    matched_rule_ids: list[str] = []

    for evidence in titles:
        title = evidence.get("title")
        if not isinstance(title, str):
            continue

        for pattern, location in ATTACHMENT_LOCATION_RULES:
            if not pattern.search(title):
                continue

            if location not in matched_locations:
                matched_locations.append(location)
            rule_id = str(location.get("rule_id", pattern.pattern))
            if rule_id not in matched_rule_ids:
                matched_rule_ids.append(rule_id)

    if not matched_locations:
        return None, [], "unmatched"

    coordinates = {
        tuple(location["inferred_coordinates"])
        for location in matched_locations
        if isinstance(location.get("inferred_coordinates"), list)
    }
    if len(coordinates) != 1:
        return None, matched_rule_ids, "ambiguous"

    return matched_locations[0], matched_rule_ids, "matched"


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


def read_gis_points(input_path: Path) -> dict[int, list[float]]:
    """Read one EPSG:2177 point for each notice number from GeoJSON."""

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Nie znaleziono pliku z punktami GIS: {input_path}"
        )

    with input_path.open(encoding="utf-8") as input_file:
        data = json.load(input_file)

    points: dict[int, list[float]] = {}
    for feature in data.get("features", []):
        properties = feature.get("properties", {})
        notice_number = properties.get("NR")
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates")

        if notice_number is None or geometry.get("type") != "Point":
            continue
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            continue

        notice_key = int(notice_number)
        point = [float(coordinates[0]), float(coordinates[1])]
        previous_point = points.get(notice_key)
        if previous_point is not None and previous_point != point:
            raise ValueError(
                f"Numer uwagi {notice_key} ma różne punkty GIS."
            )
        points[notice_key] = point

    return points


def attachment_index(notice_number: object, fragment: str) -> str | None:
    """Return a notice-scoped reference for a single attachment mention."""

    number = attachment_number(fragment)
    if number is None:
        return None

    return f"zalacznik|uwaga={notice_number}|nr={number}"


def is_excluded_from_repeated_search(fragment: str) -> bool:
    """Exclude attachment references and placeholder-only area values."""

    return "zgodnie" in fragment.casefold() or fragment.strip() == "-"


def extracted_records(
    records: Iterable[dict[str, Any]],
    gis_points: dict[int, list[float]],
    attachment_headers: dict[
        tuple[int, int], list[dict[str, object]]
    ] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build one record per area fragment and the global reference map."""

    attachment_headers = attachment_headers or {}
    area_indexes: dict[str, str] = {}
    next_area_number = 1
    extracted: list[dict[str, Any]] = []

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

            attachment_metadata: dict[str, object] = {}
            attachment_location: dict[str, object] | None = None
            attachment_number_value = attachment_number(fragment)
            if attachment_number_value is not None:
                evidence = attachment_headers.get(
                    (int(notice_number), attachment_number_value),
                    [],
                )
                attachment_location, rule_ids, match_status = (
                    match_attachment_location(evidence)
                    if evidence
                    else (None, [], "header_not_found")
                )
                attachment_metadata = {
                    "attachment_number": attachment_number_value,
                    "attachment_header_titles": [
                        item["title"]
                        for item in evidence
                        if isinstance(item.get("title"), str)
                    ],
                    "attachment_header_pages": [
                        item["page"]
                        for item in evidence
                        if isinstance(item.get("page"), int)
                    ],
                    "attachment_location_rules": rule_ids,
                    "attachment_location_status": match_status,
                }

            known_location = KNOWN_LOCATIONS.get(fragment)
            inferred_coordinates = (
                known_location.get("inferred_coordinates")
                if known_location is not None
                else None
            )
            inferred_details = (
                known_location.get("inferred_details")
                if known_location is not None
                else None
            )
            coordinates_source = (
                "known_location" if inferred_coordinates is not None else None
            )

            if inferred_coordinates is None and attachment_location is not None:
                inferred_coordinates = attachment_location.get(
                    "inferred_coordinates"
                )
                inferred_details = attachment_location.get("inferred_details")
                if inferred_coordinates is not None:
                    coordinates_source = "attachment_header_rule"

            if inferred_coordinates is None and len(fragments) == 1:
                inferred_coordinates = gis_points.get(int(notice_number))
                if inferred_coordinates is not None:
                    coordinates_source = "gis_single_area"

            extracted_record = {
                "data_wplywu": data_wplywu,
                "oznaczenie_uwagi": notice_number,
                "kolejnosc": order,
                "obszar_extracted_raw": fragment,
                "obszar_unique_index": reference,
                "inferred_coordinates": inferred_coordinates,
                "inferred_coordinates_source": coordinates_source,
                "inferred_details": inferred_details,
                "pdf_page": pdf_page,
            }
            extracted_record.update(attachment_metadata)
            extracted.append(extracted_record)

    return extracted, area_indexes


def fill_repeated_coordinates(records: list[dict[str, Any]]) -> tuple[int, int]:
    """Fill records from unambiguous matches sharing an area unique index."""

    notice_sizes = Counter(record["oznaczenie_uwagi"] for record in records)
    coordinates_by_area_index: dict[str, set[tuple[float, ...]]] = {}

    for record in records:
        if notice_sizes[record["oznaczenie_uwagi"]] != 1:
            continue
        if is_excluded_from_repeated_search(record["obszar_extracted_raw"]):
            continue

        coordinates = record["inferred_coordinates"]
        if not isinstance(coordinates, list):
            continue

        area_index = record["obszar_unique_index"]
        coordinates_by_area_index.setdefault(area_index, set()).add(
            tuple(coordinates)
        )

    unambiguous_coordinates = {
        area_index: next(iter(coordinates))
        for area_index, coordinates in coordinates_by_area_index.items()
        if len(coordinates) == 1
    }
    conflict_count = sum(
        1
        for coordinates in coordinates_by_area_index.values()
        if len(coordinates) > 1
    )
    filled_count = 0

    for record in records:
        if notice_sizes[record["oznaczenie_uwagi"]] <= 1:
            continue
        if record["inferred_coordinates"] is not None:
            continue
        if is_excluded_from_repeated_search(record["obszar_extracted_raw"]):
            continue

        coordinates = unambiguous_coordinates.get(record["obszar_unique_index"])
        if coordinates is None:
            continue

        record["inferred_coordinates"] = list(coordinates)
        record["inferred_coordinates_source"] = "repeated_single_area"
        filled_count += 1

    return filled_count, conflict_count


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


def convert(
    input_path: Path,
    output_path: Path,
    gis_input_path: Path,
    page_headers_input_path: Path = DEFAULT_PAGE_HEADERS_INPUT,
) -> tuple[int, int, int, int]:
    gis_points = read_gis_points(gis_input_path)
    attachment_headers = read_attachment_headers(page_headers_input_path)
    records, area_indexes = extracted_records(
        read_records(input_path),
        gis_points,
        attachment_headers,
    )
    filled_count, conflict_count = fill_repeated_coordinates(records)
    record_count = write_jsonl(records, output_path)
    return record_count, len(area_indexes), filled_count, conflict_count


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
    parser.add_argument(
        "--gis-input",
        type=Path,
        default=DEFAULT_GIS_INPUT,
        help=f"warstwa punktów GIS (domyślnie: {DEFAULT_GIS_INPUT})",
    )
    parser.add_argument(
        "--page-headers-input",
        type=Path,
        default=DEFAULT_PAGE_HEADERS_INPUT,
        help=(
            "nagłówki stron wniosków JSONL "
            f"(domyślnie: {DEFAULT_PAGE_HEADERS_INPUT})"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record_count, area_count, filled_count, conflict_count = convert(
        args.input,
        args.output,
        args.gis_input,
        args.page_headers_input,
    )
    print(
        f"Zapisano {record_count} rekordów i {area_count} unikalnych obszarów "
        f"do {args.output}; uzupełniono {filled_count} rekordów w drugim "
        f"przebiegu; pominięto {conflict_count} konfliktów"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
