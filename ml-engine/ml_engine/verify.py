"""Subprocess JSON protocol and optional PostgreSQL read/persistence CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from uuid import UUID

from .cpg_builder import baseline, build_cpg, combined_graph_json
from .gnn_aligner import MODEL_DIR, align
from .z3_formal_prover import SAT, UNKNOWN, UNSAT, prove

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FIELDS = ("moduleName", "category", "cobolSource", "javaSource")


def load_reference_rates() -> list[dict]:
    rates = json.loads((ROOT / "data-sources/reference-fx-rates.json").read_text())
    for rate in rates:
        rate["provenanceJson"] = {key: value for key, value in rate.items()
                                  if key not in ("currencyPair", "rate", "source", "collectedDate", "observationDate", "id")}
    corridor = json.loads((ROOT / "data-sources/remittance-corridor.json").read_text())
    rates.append({"currencyPair": "GBP/THB", "rate": corridor["displayedProviderExchangeRate"],
                  "source": corridor["source"], "collectedDate": corridor["collectedDate"],
                  "observationDate": corridor["surveyCollectionEnd"],
                  "provenanceJson": {**corridor, "rateMeaning": "historical displayed provider THB per GBP, rounded survey value"}})
    return rates


def select_rate(category: str, rates: list[dict]) -> dict:
    # The category selects input data only; neither the parser nor solver use it
    # to decide status, arithmetic, graph matches or bug presence.
    if not rates:
        raise ValueError("At least one provenance-labelled reference FX rate is required")
    if category == "REMITTANCE_FEE":
        matches = [rate for rate in rates if rate["currencyPair"] == "GBP/THB" and "World Bank" in rate["source"]]
    else:
        matches = [rate for rate in rates if rate["currencyPair"] == "GBP/EUR"]
    return dict((matches or rates)[0])


def verify_request(request: dict) -> dict:
    if not isinstance(request, dict):
        raise ValueError("Request must be a JSON object")
    for key in REQUIRED_FIELDS:
        value = request.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a nonempty string")
        if len(value) > 100000 or value.count("\n") > 1500:
            raise ValueError(f"{key} exceeds the documented 100000-character/1500-line limit")
    if "patchedJavaSource" in request and (not isinstance(request["patchedJavaSource"], str) or len(request["patchedJavaSource"]) > 100000 or request["patchedJavaSource"].count("\n") > 1500):
        raise ValueError("patchedJavaSource must be a string within source limits when supplied")
    rates = request.get("referenceFxRates")
    if rates is None:
        rates = load_reference_rates()
    if not isinstance(rates, list) or not all(isinstance(rate, dict) for rate in rates):
        raise ValueError("referenceFxRates must be an array")
    for rate in rates:
        for key in ("currencyPair", "rate", "source", "collectedDate"):
            if key not in rate or not str(rate[key]).strip():
                raise ValueError(f"Reference rate requires {key}")
        date.fromisoformat(rate["collectedDate"])
    cobol = build_cpg(request["cobolSource"], "cobol")
    java = build_cpg(request["javaSource"], "java")
    alignment = align(cobol, java)
    baseline_score, baseline_caught = baseline(request["cobolSource"], request["javaSource"])
    rate = select_rate(request["category"], rates)
    proof = prove(request["cobolSource"], request["javaSource"], rate)
    status = proof["formalProofStatus"]
    if status == SAT:
        witness = proof["counterexamplesJson"][0]
        explanation = (f"Z3 found amount {witness['inputAmountGbp']} GBP: COBOL {witness['cobolOutput']}, "
                       f"Java {witness['javaOutput']}, drift {witness['pennyDrift']} output units. "
                       f"Rate {rate['rate']} ({rate['source']}; observed {rate.get('observationDate', 'unspecified')}).")
    elif status == UNSAT:
        bounds = proof["proofScope"]["inputAmountCents"]
        explanation = (f"Z3 UNSAT: no differing cent-observable outputs for integer cents in "
                       f"[{bounds['min']}, {bounds['max']}] with exact rate {rate['rate']}. "
                       "This is equivalence of the supported bounded scalar model.")
    else:
        explanation = f"Proof halted: {proof['proofScope'].get('reason', 'unsupported semantics')}. Human review is required."
    summary = (f"Structural GCN alignment cosine {alignment['alignmentScore']:.3f}; synthetic-calibrated node risk "
               f"{alignment['bugRiskScore']:.3f}. Factors: {', '.join(alignment['riskFactors'])}. {explanation}")
    return {"gnnAlignmentScore": alignment["alignmentScore"], "gnnBugRiskScore": alignment["bugRiskScore"],
            "baselineAlignmentScore": baseline_score, "baselineCaughtBug": baseline_caught,
            **proof, "fStringSummary": summary,
            "cpgGraphJson": combined_graph_json(cobol, java, alignment["links"]),
            "provenanceJson": {"engineVersion": "0.1.0", "model": alignment["modelProvenance"],
                "modelSha256": hashlib.sha256((MODEL_DIR / "cobol_java_gnn_v1.json").read_bytes()).hexdigest(),
                "graphInferenceMs": alignment["inferenceMs"], "referenceRate": rate,
                "alignmentIsProof": False, "measuredAlignmentBenchmark": None,
                "sourceAuthorship": request.get("sourceAuthorship", "Caller-supplied sources; provenance not independently verified"),
                "limitations": ["Structural graph extraction is a source-line approximation, separate from the closed formal parser.",
                                "GNN/model confidence is not proof and does not prune symbolic inputs.",
                                "Synthetic model calibration does not establish financial defect accuracy."]}}


def _database_url() -> str:
    # Read .env without executing shell content or overwriting process variables.
    values = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.fullmatch(r"\s*([A-Z_]+)\s*=\s*(.*?)\s*", line)
            if match:
                values[match[1]] = match[2].strip('"\'')
    result = os.environ.get("DATABASE_URL") or values.get("DATABASE_URL")
    if not result:
        raise ValueError("DATABASE_URL is required for --id/--persist (environment or root .env)")
    return result


def load_database_request(verification_id: str) -> dict:
    import psycopg
    from psycopg.rows import dict_row
    UUID(verification_id)
    with psycopg.connect(_database_url(), row_factory=dict_row) as connection:
        row = connection.execute("SELECT id,module_name,category,cobol_source,java_source,patched_java_source,version FROM verifications WHERE id=%s", (verification_id,)).fetchone()
        if row is None:
            raise ValueError("Verification not found")
        rates = connection.execute("SELECT currency_pair,rate,source,collected_date,observation_date,provenance_json FROM reference_fx_rates ORDER BY source,currency_pair").fetchall()
    return {"id": str(row["id"]), "expectedVersion": row["version"], "moduleName": row["module_name"], "category": row["category"],
            "cobolSource": row["cobol_source"], "javaSource": row["java_source"], "patchedJavaSource": row["patched_java_source"],
            "referenceFxRates": [{"currencyPair": rate["currency_pair"], "rate": str(rate["rate"]),
                                  "source": rate["source"], "collectedDate": rate["collected_date"],
                                  "observationDate": rate["observation_date"], "provenanceJson": rate["provenance_json"]} for rate in rates]}


def persist_database_result(request: dict, result: dict):
    import psycopg
    from psycopg.types.json import Jsonb
    verification_id = request["id"]
    UUID(verification_id)
    fields = {"gnn_alignment_score": result["gnnAlignmentScore"], "gnn_bug_risk_score": result["gnnBugRiskScore"],
              "baseline_alignment_score": result["baselineAlignmentScore"], "baseline_caught_bug": result["baselineCaughtBug"],
              "formal_proof_status": result["formalProofStatus"], "bug_category": result["bugCategory"],
              "f_string_summary": result["fStringSummary"], "cpg_graph_json": Jsonb(result["cpgGraphJson"]),
              "counterexamples_json": Jsonb(result["counterexamplesJson"]), "is_failure_limit_case": result["isFailureLimitCase"],
              "proof_scope": Jsonb(result["proofScope"]), "provenance_json": Jsonb(result["provenanceJson"])}
    with psycopg.connect(_database_url()) as connection:
        # All identifiers are an internal constant map; input values are bound.
        sql = "UPDATE verifications SET " + ", ".join(f"{key}=%s" for key in fields) + ",updated_at=now(),version=version+1 WHERE id=%s AND version=%s AND cobol_source=%s AND java_source=%s"
        cursor = connection.execute(sql, (*fields.values(), verification_id, request["expectedVersion"], request["cobolSource"], request["javaSource"]))
        if cursor.rowcount != 1:
            raise ValueError("Verification was deleted or changed during analysis; stale --persist rejected")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stdin", action="store_true", help="Consume one JSON request; emit one JSON analysis result")
    mode.add_argument("--id", help="Load existing verification and reference rates from PostgreSQL")
    parser.add_argument("--persist", action="store_true", help="Update analysis of existing UUID row; requires --id")
    arguments = parser.parse_args()
    try:
        if arguments.persist and not arguments.id:
            raise ValueError("--persist requires --id, so source and analysis cannot become inconsistent")
        if arguments.stdin:
            payload = sys.stdin.read(1048577)
            if len(payload.encode("utf-8")) > 1048576:
                raise ValueError("JSON request exceeds 1 MiB")
            request = json.loads(payload)
        else:
            request = load_database_request(arguments.id)
        result = verify_request(request)
        if arguments.persist:
            persist_database_result(request, result)
        print(json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":")))
    except Exception as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
