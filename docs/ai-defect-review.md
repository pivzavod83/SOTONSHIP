# AI defect review of a supplied COBOL–Java pair

This feature asks a coding LLM where the supplied Java may fail to preserve the supplied COBOL. It does not need to retrieve a matching program first. The model supplies explanations, source-line references, possible correction descriptions and candidate test inputs. The application validates their structure and source references; it does not validate the model's semantic judgment.

The existing GNN still performs optional program matching. Z3 still independently checks its supported bounded financial subset. Neither the GNN score nor an AI review changes a formal proof result or authorizes a patch.

## Enable the provider

Copy `.env.example` to `.env` if no local configuration exists. Set these values in the root `.env` or `backend/.env`, then restart the backend:

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=your-deployed-coding-model
LLM_API_KEY=your-provider-key
LLM_RESPONSE_FORMAT=json_schema
LLM_TIMEOUT_SECONDS=60
LLM_MAX_COMPLETION_TOKENS=4096
```

Choose a coding model available in your provider account. The configured base URL must expose `POST <base>/chat/completions`. There is no hardcoded model choice. Remote providers require HTTPS and a key. An explicit loopback provider such as `http://127.0.0.1:11434/v1` may omit the key, but must expose the same protocol and accept the configured model and token parameter. Other compatible providers can use their own base URL and key.

`json_schema` requests strict structured output. Use `json_object` only if your provider supports JSON mode without strict schemas, or `text` for a provider that needs the schema in the prompt without a response-format parameter. All three modes undergo the same local output validation. There is no automatic fallback or retry that could silently change behavior or cause extra billed requests. Incompatible models return an explicit error; check their supported Chat Completions parameters before choosing one. The protocol follows the [official structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat).

The timeout must be 1–90 seconds and the completion budget 256–8192 tokens. The shared Python worker also has its own overall time budget (`ML_TIMEOUT_MS`, default 120000). Keep the editor request timeout long enough for the worker queue and provider call. The queue is bounded and not durable.

Keys stay in the backend environment and are not accepted in requests or editor settings. The AI action sends the exact selected source text, module name, source format and analysis context to that provider. It sends no database credentials, FX database rows or unrelated workspace files. Source transmission occurs only when the engineer explicitly requests AI review. Use a provider suitable for the code you choose to submit.

Blank model/key configuration returns `NOT_CONFIGURED`, with no invented findings. A loopback provider still requires a configured model. The repository does not ship credentials or a running language model.

## Use the local browser UI

Start the Nest backend, then run `npm run ui` from `backend/`. Open `http://127.0.0.1:3000`; the default proxied API is `http://127.0.0.1:3003`. Set `API_URL` to another backend port when needed. The browser UI and backend both load the documented local configuration; restart them after changing provider settings.

The page opens with a recorded, actually executed COBOL/Java mismatch and highlighted source lines. It labels this `CONFIRMED_REPLAY`, independently of AI. The [raw evidence and explicit COBOL input/output harness](../backend/dev-ui/data/README.md) record GnuCOBOL 53.24, original Java 53.23 and corrected Java 53.24 for amount 45.00 and rate 1.1830. This is a genuine behavior difference in an AI-authored educational fixture, not a production-bank case or a fabricated LLM response.

Use **Analyze pair with AI** for a live model review of the current editor contents. It remains unavailable until credentials/model are configured or a compatible loopback model server is running. Use **Run Z3 verification** independently, or load the prewritten corrected Java and reverify. Editing sources/context invalidates older findings; the recorded replay is displayed only for its exact source hashes. The API does not execute arbitrary submitted programs. Offline replay is restricted to the pinned reviewed fixture.

A local model is an alternative to a hosted API; the repository does not bundle one. Existing GNN weights perform program matching and cannot be reused as a trained defect detector without new labelled training/evaluation work.

## Use it in VS Code

1. Start the existing PostgreSQL/backend services and install the rebuilt extension as described in its [README](../vscode-extension/README.md).
2. Open **SOTONSHIP: Open Verification Workbench** and select the COBOL source and its Java translation. Current unsaved text is used.
3. Set the AI source format and optionally describe input/output mapping, entry points or relevant migration assumptions. This context helps the model; it is not a formal contract.
4. Click **Analyze pair with AI**, or run **SOTONSHIP: Analyze Pair with AI**. Inspect the source-linked hypotheses and limitations.
5. For a supported financial pair, run the existing independent verification using explicit proof inputs. For broader programs, check a hypothesis with a separately controlled test harness or human review. Automatic execution of proposed inputs is not implemented.

Review results are invalidated when source documents, document versions, selected files, backend URL, analysis context or AI source format change. Late responses for old sources are marked stale and their findings hidden; exported reports retain the stale flag. AI findings do not become verified Problems diagnostics or edits. To change Java, supply a candidate yourself and use the existing diff and fresh-verification flow.

## HTTP and CLI

`POST /api/ai-reviews` accepts:

```json
{
  "moduleName": "Example",
  "cobolSource": "...complete original source...",
  "javaSource": "...complete candidate source...",
  "cobolSourceFormat": "FREE",
  "analysisContext": "Describe entry points and input/output mapping, if known."
}
```

Each source is limited to 100000 characters and 1500 LF-separated lines. The complete JSON-encoded request is limited to 1000000 UTF-8 bytes; malformed Unicode and null bytes are rejected by the API. The module name is limited to 160 characters and context to 8000. No provider URL, key, executable harness or proof flag is accepted in this request.

To try the existing educational FX fixture, create a request from the repository root:

```sh
python3 - <<'PY' > /tmp/sotonship-ai-review.json
import json
from pathlib import Path
fixtures = Path('ml-engine/data/fixtures')
print(json.dumps({
    'moduleName': 'FX-WIRE-CALC',
    'cobolSource': (fixtures / 'FX-WIRE-CALC.cbl').read_text(),
    'javaSource': (fixtures / 'FX-WIRE-CALC.java.txt').read_text(),
    'cobolSourceFormat': 'FREE',
    'analysisContext': 'Compare returned monetary values, with the same amount and exchange rate.'
}))
PY
curl --fail-with-body http://127.0.0.1:3001/api/ai-reviews \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/sotonship-ai-review.json
```

The read-only API uses Controller → QueryBus → handler → application engine port → Python adapter. It creates no database row. With variables exported in your shell, the same engine can run directly:

```sh
cd ml-engine
.venv/bin/python -m ml_engine.ai_review --stdin < /tmp/sotonship-ai-review.json
```

The standalone Python command does not load `.env` files automatically. The backend loads them before spawning the worker.

## Interpret a result

| Field/status | Meaning |
| --- | --- |
| `ANALYZED` | A structurally valid review was received. It may have zero findings. |
| `NOT_CONFIGURED` | Required settings are absent or invalid; no provider request was made. |
| `PROVIDER_ERROR` | Connection, timeout or HTTP failure; no findings accepted. |
| `INVALID_MODEL_OUTPUT` | Invalid/truncated JSON, out-of-range anchors or schema violation; no findings accepted. |
| `REFUSED` | The provider declined the review; no findings accepted. |
| `evidenceStatus: AI_HYPOTHESIS` | A model opinion requiring independent confirmation. |
| Candidate input `status: NOT_EXECUTED` | A suggested JSON input object, not a reproduced counterexample. |
| `aiIsProof: false` / `counterexamplesExecuted: false` | AI review establishes neither proof nor executed evidence. |

Findings have a category, qualitative severity, explanation, one-based COBOL/Java line spans, exact excerpts, a possible fix description and up to three proposed input objects. Up to eight findings are accepted. A missing safe correction can be an empty description. At least one source span is required per finding. Both sources retain their raw text and SHA-256 hashes; line boundaries split on LF without normalizing CR or Unicode. Hashes identify the exact submitted text, not semantic equivalence.

The model is instructed to preserve the actual COBOL behavior, including unusual algorithms, picture width, rounding, initialization, index conventions and paragraph flow. That instruction helps focus the review; it cannot guarantee correctness. Line validation proves only that an anchor exists, not that the model selected the true defect location. An empty review is not a safety claim. Severity is not a calibrated probability.

## What was validated, and what remains

Python tests exercise the actual HTTP adapter with a local mock provider, strict JSON/schema validation, source binding, timeouts, response limits, refusal and failure paths. Backend tests cover CQRS/DDD boundaries and result validation. Extension tests cover request handling and stale-source protection. From `backend/`, after `npm run build`, `npm run test:ai-review:smoke` starts a database-free Nest module and local mock provider to test HTTP → CQRS → real Python → provider protocol → validated response. It needs no key, database or internet access.

These checks establish integration behavior only. No real model accuracy, defect recall, latency or repair success is claimed. A live provider call requires your credentials/model configuration. The six known source-task defect families in the existing corpus are development demonstration cases, not an unseen accuracy benchmark. This feature neither retrains the GNN nor uses the 23 reserved families for training or evaluation.

Automatic translation, patch generation/application from AI, and execution of model-proposed tests remain unimplemented. A later improvement is an isolated, contract-checked witness runner; it must establish actual same-input behavior before calling a proposed input a confirmed counterexample. The current API never compiles or executes submitted source.

This integration, prompt, tests and documentation were AI-generated and require human review. Upstream code and financial data retain their existing licences and provenance.
