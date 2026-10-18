#!/usr/bin/env python3
"""Inventory pinned reviewed translation annotations; never execute or train code.

The input is artifacts.zip from Zenodo record10447705. Annotations, translation
identifiers, independent original problems and reproduced defects are different
units. This script counts the first two only. All training admission stays zero.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ARTIFACT_URL = 'https://zenodo.org/api/records/10447705/files/artifacts.zip/content'
ARCHIVE_MD5 = 'af77884df386d1662d7f92a1cecc42d2'
ARCHIVE_SHA256 = 'cdcb44e325ff41d4880f387d78fc7169d8736c3af793b0345d2c19dd76be7d2b'
LABEL_MEMBER = 'Artifacts/RQ2-Manual Labeling/manual labeling.xlsx'
LABEL_SHA256 = 'ce9e9f24ffbcb23a55574688483c667c8aedec4dbc8bd45ff699be810ce359fe'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def language(value: str) -> str:
    value = value.strip().lower()
    return {'py': 'python', 'c++': 'cpp'}.get(value, value)


def translation_key(row: dict) -> tuple:
    return (row['A'].strip().lower(), language(row['B']), language(row['C']), row['D'].strip())


def impact(row: dict) -> str:
    return ' '.join(row.get('H', 'MISSING').strip().lower().split())


def read_annotations(archive: Path) -> tuple[bytes, bytes, list[dict]]:
    archive_bytes = archive.read_bytes()
    if (hashlib.sha256(archive_bytes).hexdigest() != ARCHIVE_SHA256
            or hashlib.md5(archive_bytes).hexdigest() != ARCHIVE_MD5):
        raise ValueError('Expected the exact pinned Zenodo10447705 artifacts.zip.')
    with ZipFile(BytesIO(archive_bytes)) as bundle:
        workbook_bytes = bundle.read(LABEL_MEMBER)
    if hashlib.sha256(workbook_bytes).hexdigest() != LABEL_SHA256:
        raise ValueError('Pinned manual annotation workbook changed.')
    with ZipFile(BytesIO(workbook_bytes)) as workbook:
        shared = [''.join(item.itertext()) for item in ET.fromstring(workbook.read('xl/sharedStrings.xml'))]
        sheet = ET.fromstring(workbook.read('xl/worksheets/sheet1.xml'))
    rows = []
    for row in sheet.findall('.//s:sheetData/s:row', NS):
        values = {}
        for cell in row.findall('s:c', NS):
            value = cell.find('s:v', NS)
            if value is not None and value.text:
                values[re.sub(r'\d', '', cell.attrib['r'])] = shared[int(value.text)] if cell.get('t') == 's' else value.text
        if values:
            rows.append(values)
    header = rows.pop(0)
    if [header.get(c) for c in 'ABCDEH'] != ['Dataset', 'Source Language', 'Target Language', 'Filename', 'BugType', 'Impact']:
        raise ValueError('Unexpected annotation sheet schema.')
    if any(not all(row.get(c, '').strip() for c in 'ABCDEH') for row in rows):
        raise ValueError('Annotation rows are missing required provenance/label fields.')
    return archive_bytes, workbook_bytes, rows


def summary(rows: list[dict]) -> dict:
    impacts = sorted({impact(row) for row in rows})
    return {
        'annotationRows': len(rows),
        'distinctTranslationIds': len({translation_key(row) for row in rows}),
        'sourceLanguageAnnotationCounts': dict(Counter(language(row['B']) for row in rows)),
        'targetLanguageAnnotationCounts': dict(Counter(language(row['C']) for row in rows)),
        'impactAnnotationCounts': dict(Counter(impact(row) for row in rows)),
        'distinctTranslationIdsByImpact': {label: len({translation_key(row) for row in rows if impact(row) == label}) for label in impacts},
        'bugTypeAnnotationCounts': dict(Counter(row['E'] for row in rows)),
        'datasetAnnotationCounts': dict(Counter(row['A'] for row in rows)),
    }


def audit(archive: Path, collected_date: str) -> dict:
    date.fromisoformat(collected_date)
    archive_bytes, _, rows = read_annotations(archive)
    java = [row for row in rows if language(row['C']) == 'java']
    result = {
        'schemaVersion': 1, 'collectedDate': collected_date, 'status': 'METADATA_AUDIT_ONLY',
        'source': {'record': 'https://zenodo.org/records/10447705', 'download': ARTIFACT_URL,
            'archiveBytes': len(archive_bytes), 'publishedMd5': ARCHIVE_MD5, 'archiveSha256': ARCHIVE_SHA256,
            'manualLabelsMember': LABEL_MEMBER, 'manualLabelsSha256': LABEL_SHA256,
            'datasetLicense': 'CC-BY-4.0; preserve additional upstream source-code licences'},
        'allAnnotations': summary(rows), 'targetJava': summary(java),
        'cobolAnnotations': sum(language(row['B']) == 'cobol' or language(row['C']) == 'cobol' for row in rows),
        'executionPerformed': False, 'modelTrainingPerformed': False, 'labelsAdmittedForTraining': 0,
        'limitations': [
            'Multiple annotations can describe one translation. Translation IDs are not independent original problems or projects.',
            'Impact-specific distinct counts overlap when one translation has multiple impact labels; do not sum them.',
            'The authors reviewed naturally occurring model translation failures, not injected mutations; this is not a production human-migration corpus.',
            'No local source-code joins, reproductions, fix validation, healthy controls or cross-corpus leakage checks have been completed.',
            'Compilation, runtime, wrong-output, no-output and nontermination outcomes require separate study targets.',
            'There are no COBOL annotations. Results on other languages cannot establish COBOL-to-Java defect accuracy.',
        ],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--collected-date', required=True, help='Actual audit date YYYY-MM-DD')
    parser.add_argument('--output', type=Path, help='New JSON evidence file; refuses overwriting')
    args = parser.parse_args()
    result = audit(args.archive, args.collected_date)
    encoded = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as handle:
            handle.write(encoded)
    else:
        print(encoded, end='')


if __name__ == '__main__':
    main()
