"""Regenerate four honest seed analyses from source, saved model and Z3."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .fixtures import demo_requests
from .verify import ROOT, load_reference_rates, verify_request
from .z3_formal_prover import UNKNOWN, UNSAT


def precompute(output: Path) -> dict:
    rates = load_reference_rates()
    for rate in rates:
        rate["id"] = str(uuid5(NAMESPACE_URL, "sotonship:rate:" + rate["currencyPair"] + ":" + rate["source"] + ":" + rate["collectedDate"]))
    rows = []
    timestamp = datetime.now(timezone.utc).isoformat()
    for request in demo_requests():
        authored = {"aiGenerated": True, "description": "AI-authored executable scalar COBOL/Java banking demonstration",
                    "inspiration": "Apache-2.0 IBM/Bank-of-Z COBOL, pinned source attribution in data-sources/provenance.json",
                    "authenticVendorExtract": False,
                    "remittancePolicy": "Historical World Bank GBP120 fee1.89 plus AI-generated >GBP120 tier at1%; not a real provider tariff"}
        request.update(referenceFxRates=rates, sourceAuthorship=authored)
        result = verify_request(request)
        # Each advertised patch is genuinely rechecked; external case has no
        # certified patch and retains UNKNOWN, rather than inventing a proof.
        patch_request = {**request, "javaSource": request["patchedJavaSource"]}
        patch = verify_request(patch_request)
        expected = UNKNOWN if request["category"] == "EXTERNAL_LIMIT_CASE" else UNSAT
        if patch["formalProofStatus"] != expected:
            raise RuntimeError(f"Patch validation failed for {request['moduleName']}: {patch['proofScope']}")
        result["provenanceJson"]["patchVerification"] = {"status": patch["formalProofStatus"], "proofScope": patch["proofScope"]}
        row = {key: value for key, value in request.items() if key not in ("referenceFxRates", "sourceAuthorship")}
        rows.append({**row, **result, "createdAt": timestamp, "updatedAt": timestamp})
        fixture_dir = output.parent / "fixtures"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        (fixture_dir / request["moduleName"]).write_text(request["cobolSource"])
        stem = request["moduleName"].removesuffix(".cbl")
        (fixture_dir / f"{stem}.java.txt").write_text(request["javaSource"])
        (fixture_dir / f"{stem}.patched.java.txt").write_text(request["patchedJavaSource"])
    artifact = {"formatVersion": 1, "generatedAt": timestamp,
                "provenance": "AI-authored financial test fixtures, excluded from paired-code GNN training; recomputed independent Z3 results. Raw reference-data provenance retained.",
                "referenceFxRates": rates, "verifications": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "ml-engine/data/seed-verifications.json")
    arguments = parser.parse_args()
    artifact = precompute(arguments.output)
    print(json.dumps({"output": str(arguments.output), "modules": [{"id": row["id"], "moduleName": row["moduleName"],
                       "status": row["formalProofStatus"]} for row in artifact["verifications"]]}))


if __name__ == "__main__":
    main()
