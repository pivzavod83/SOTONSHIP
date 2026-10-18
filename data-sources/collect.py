#!/usr/bin/env python3
"""Refresh public source snapshots using Python's standard library.

Pass --collected-date explicitly when reproducing; it is the retrieval date, not
the date of an FX observation. The World Bank page extract was verified through
the web research tool because its origin rejects non-browser downloads (403).
"""
import argparse
import hashlib
import html
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMIT = "a570aa467cd41b4400db1d6db168d17e886dd136"
BOE_URL = (
    "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp?"
    "CSVF=TT&DAT=RNG&FD=1&FM=Jan&FNY=Y&FY=2021&Filter=N&FromSeries=1&"
    "SeriesCodes={series}&TD=17&TM=Oct&TY=2026&ToSeries=50&"
    "Travel=NIxAZxSUx&UsingCodes=Y&VPD=Y&html.x=66&html.y=26&title={series}"
)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_manifest(sources, collection_date):
    corridor_path = ROOT / "remittance-corridor.json"
    if corridor_path.exists():
        corridor = json.loads(corridor_path.read_text())
        snapshot_path = corridor["provenance"]["snapshotPath"]
        sources.append({
            "id": corridor["id"], "provider": corridor["source"],
            "url": corridor["sourceUrl"], "collectedDate": corridor["collectedDate"],
            "surveyCollectionStart": corridor["surveyCollectionStart"],
            "surveyCollectionEnd": corridor["surveyCollectionEnd"],
            "snapshotPath": snapshot_path,
            "sha256": digest((ROOT / snapshot_path).read_bytes()),
            "snapshotType": corridor["provenance"]["snapshotType"],
            "rawHttpResponseArchived": False,
            "licence": corridor["licence"], "licenceUrl": corridor["licenceUrl"],
            "attribution": corridor["attribution"],
            "limitations": corridor["limitations"],
        })
    write_json(ROOT / "provenance.json", {
        "schemaVersion": 1,
        "collectionDate": collection_date,
        "collectionTimezone": "Europe/London",
        "collectionDateBasis": "User-provided client date; observation and survey dates retain their provider vintage.",
        "desiredFxObservationDate": "2026-10-16",
        "queryEndDate": "2026-10-17",
        "fxDateLimitation": "Latest observation returned by archived responses is 2026-10-15. No 2026-10-16 quote or rate 1.2941 is asserted.",
        "aiGenerated": [
            "Collector, metadata, numeric transcription and documentation were prepared by an AI coding assistant.",
            "The financial verifier's four educational fixtures and Java migrations are AI-generated; IBM extracts are separate unmodified reference material.",
            "Any tiered fee policy used by the verifier is an illustrative generated formula, not a published World Bank or Wise tariff.",
        ],
        "sources": sources,
        "hashAlgorithm": "SHA-256",
        "hashMeaning": "Integrity of archived local bytes. For manually transcribed data, the hash is not an upstream HTTP-response checksum.",
    })
    paths = sorted(path for path in ROOT.rglob("*") if path.is_file() and path.name != "checksums.sha256" and "__pycache__" not in path.parts)
    (ROOT / "checksums.sha256").write_text("".join(f"{digest(path.read_bytes())}  {path.relative_to(ROOT).as_posix()}\n" for path in paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collected-date", required=True)
    args = parser.parse_args()
    datetime.strptime(args.collected_date, "%Y-%m-%d")
    (ROOT / "snapshots").mkdir(parents=True, exist_ok=True)
    (ROOT / "cobol").mkdir(exist_ok=True)
    rates = []
    sources = []
    for pair, series in [("GBP/EUR", "XUDLERS"), ("GBP/USD", "XUDLUSS"), ("GBP/THB", "XUDLBK87")]:
        url = BOE_URL.format(series=series)
        raw = fetch(url)
        snapshot = f"snapshots/boe-{series}.html"
        (ROOT / snapshot).write_bytes(raw)
        rows = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", raw.decode(), re.S | re.I):
            text = html.unescape(re.sub(r"<[^>]+>", " ", row))
            match = re.fullmatch(r"\s*(\d{2} [A-Za-z]{3} \d{2})\s+([\d.]+)\s*", text)
            if match:
                date = datetime.strptime(match[1], "%d %b %y").date().isoformat()
                if date <= "2026-10-16":
                    rows.append((date, match[2]))
        if not rows:
            raise ValueError(f"No observations parsed for {series}")
        observed_date, rate = max(rows)
        rates.append({
            "currencyPair": pair,
            "rate": rate,
            "source": "Bank of England Daily Spot Rate",
            "collectedDate": args.collected_date,
            "observationDate": observed_date,
            "seriesCode": series,
            "sourceUrl": url,
            "licence": "OGL-UK-3.0",
            "provenance": {
                "id": f"boe-{series}",
                "units": f"{pair.split('/')[1]} per 1 GBP",
                "snapshotPath": snapshot,
                "snapshotSha256": digest(raw),
                "requestedObservationThrough": "2026-10-17",
                "desiredDemoObservationDate": "2026-10-16",
                "datePolicy": "Latest observation returned by the provider, never relabelled to the retrieval date.",
            },
        })
        sources.append({
            "id": f"boe-{series}", "provider": "Bank of England",
            "url": url, "collectedDate": args.collected_date,
            "observationDate": observed_date, "snapshotPath": snapshot,
            "sha256": digest(raw), "licence": "OGL-UK-3.0",
            "licenceUrl": "https://www.bankofengland.co.uk/legal",
            "attribution": "Source: Bank of England. Contains public sector information licensed under the Open Government Licence v3.0.",
        })
    write_json(ROOT / "reference-fx-rates.json", rates)

    base = f"https://raw.githubusercontent.com/IBM/Bank-of-Z/{COMMIT}/"
    licence = fetch(base + "LICENSE")
    (ROOT / "cobol" / "LICENSE.Apache-2.0.txt").write_bytes(licence)
    for name, ranges in [("XFRFUN", [(1, 8), (59, 96), (975, 995)]), ("BNK1TFN", [(1, 8), (88, 110), (351, 375)])]:
        upstream_path = f"src/base/cics/cobol/{name}.cbl"
        raw = fetch(base + upstream_path)
        lines = raw.decode().splitlines(keepends=True)
        excerpt = "".join("".join(lines[start - 1:end]) for start, end in ranges)
        path = f"cobol/{name}.excerpt.cbl"
        (ROOT / path).write_text(excerpt)
        sources.append({
            "id": f"ibm-{name.lower()}", "provider": "IBM / Bank-of-Z",
            "url": f"https://github.com/IBM/Bank-of-Z/blob/{COMMIT}/{upstream_path}",
            "downloadUrl": base + upstream_path, "revision": COMMIT,
            "collectedDate": args.collected_date, "upstreamSha256": digest(raw),
            "snapshotPath": path, "sha256": digest(excerpt.encode()),
            "upstreamLineRanges": ranges,
            "transformation": "Concatenated verbatim line ranges; incomplete reference excerpts, not standalone compilable programs.",
            "licence": "Apache-2.0", "licencePath": "cobol/LICENSE.Apache-2.0.txt",
            "attribution": "Copyright IBM Corp. 2023",
        })
    write_json(ROOT / "collected-sources.json", sources)
    build_manifest(sources, args.collected_date)
    print(json.dumps({"rates": [{k: x[k] for k in ("currencyPair", "rate", "observationDate", "collectedDate")} for x in rates], "sources": len(sources)}, indent=2))


if __name__ == "__main__":
    main()
