"""Engineer review reports grounded in parser/solver evidence, never LLM assertions."""
from __future__ import annotations

from .policy import ENGINE_VERSION


def build_review_report(result: dict, graph: dict, alignment: dict) -> dict:
    status = result["formalProofStatus"]
    scope = result["proofScope"]
    witness = result["counterexamplesJson"]
    safe = status == "UNSAT_PROVEN_SAFE"
    mismatch = status == "SAT_COUNTEREXAMPLE_FOUND"
    title = "Equivalent within the recorded model" if safe else "A financial output mismatch was found" if mismatch else "Verification requires human investigation"
    explanation = ("No unequal cent-observable output exists inside the recorded input domain and fixed reference rate."
                   if safe else "The concrete input below produces different modeled outputs; inspect the referenced code and decimal/control-flow rules."
                   if mismatch else scope.get("reason", "The verifier cannot model the program completely."))
    relevant = []
    for node in graph["nodes"]:
        if node.get("line") and (node.get("declaredType") in ("double", "COMP-3") or node.get("operation") in ("perform", "branch", "store", "return")):
            relevant.append({"language":node["language"],"line":node["line"],"kind":node["kind"],"label":node["label"],
                             "basis":"declared type or parsed operation; inspection hint, not a proven root cause"})
    return {"reportVersion":1,"engineVersion":ENGINE_VERSION,"disposition":"READY_FOR_REVIEW" if safe else "NEEDS_REVIEW",
            "humanReviewStatus":"PENDING","formalProofStatus":status,"equivalentWithinScope":safe,
            "title":title,"explanation":explanation,"reasonCode":scope.get("reasonCode"),
            "witnesses":witness,"relevantLocations":relevant[:16],"deterministicDiagnostics":alignment.get("diagnostics",[]),
            "alignmentStatus":alignment.get("alignmentStatus","UNKNOWN"),"proofScope":scope,
            "nextSteps":["Inspect the code, input/output mapping and proof bounds before accepting the candidate."] if safe else
                        ["Replay the supplied counterexample.","Inspect decimal scale, rounding, storage width and paragraph/control flow.","Submit revised Java and re-run verification."] if mismatch else
                        ["Inspect the stated unsupported construct or resource limit.","Provide a smaller supported calculation unit or request an engineer review."],
            "limitations":["Review locations are deterministic inspection hints; a counterexample establishes output inequality, not a complete root-cause analysis.",
                           "Human approval is separate from the mathematical proof status.","No translation or repair provider is connected."]}
