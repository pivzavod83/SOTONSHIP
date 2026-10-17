"""The same version and input/complexity policy consumed by the NestJS API."""
from __future__ import annotations

import json
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / "verification-policy.json"
POLICY = json.loads(POLICY_PATH.read_text())
ENGINE_VERSION = POLICY["engineVersion"]
SEMANTICS_VERSION = POLICY["semanticsVersion"]
MAX_SOURCE_CHARACTERS = POLICY["maxSourceCharacters"]
MAX_SOURCE_LINES = POLICY["maxSourceLines"]
MAX_JSON_BYTES = POLICY["maxJsonBytes"]
MAX_AST_NESTING = POLICY["maxAstNesting"]
MAX_EXECUTION_STEPS = POLICY["maxExecutionSteps"]
MAX_EXPRESSION_NODES = POLICY["maxExpressionNodes"]
MAX_GRAPH_NODES = POLICY["maxGraphNodes"]
SOLVER_TIMEOUT_MS = POLICY["solverTimeoutMs"]


class InputValidationError(ValueError):
    """Protocol/input errors are distinct from unsupported program semantics."""

    def __init__(self, message: str, code: str = "input.invalid"):
        super().__init__(message)
        self.code = code


def validate_source(source: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(source, str) or (not allow_empty and not source.strip()):
        raise InputValidationError(f"{field} must be a {'string' if allow_empty else 'nonempty string'}", "input.invalid_source")
    if len(source) > MAX_SOURCE_CHARACTERS:
        raise InputValidationError(f"{field} exceeds {MAX_SOURCE_CHARACTERS} characters", "input.source_too_large")
    # splitlines recognizes both CR and LF, matching the HTTP validator.
    if len(source.splitlines()) > MAX_SOURCE_LINES:
        raise InputValidationError(f"{field} exceeds {MAX_SOURCE_LINES} lines", "input.too_many_lines")
    return source
