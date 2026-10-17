# Project Summary

COBOL-to-Java migrations can change rounding, numeric capacity or control flow even when the new code looks plausible. This hackathon prototype provides an evidence-based review gate for a deliberately small financial arithmetic subset.

A developer supplies COBOL and Java. Typed graphs expose paragraphs, methods and data flow; deterministic rules highlight type/operator differences, while an experimental graph model suggests structural matches. Z3 independently checks the supported bounded semantics and returns either a concrete differing transaction, equivalence within the recorded scope, or an explicit unsupported/limit result.

Engineers can inspect a report, submit revised Java, retain source/analysis history, and apply a candidate only after fresh bounded verification succeeds. Four generated educational cases demonstrate penny drift, paragraph/width differences, a safe remittance calculation and external CICS state requiring review.

This is currently a verifier, not a translator. A provider-neutral API-key configuration holder is present, but no LLM is connected. The synthetic-trained graph model has no validated real-code alignment accuracy. The prototype does not certify arbitrary banking programs or replace human approval.
