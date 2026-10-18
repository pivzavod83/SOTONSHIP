import { createHash } from 'node:crypto';
import { InfrastructureException } from '../../../../common/exceptions/infrastructure.exception';
import { JsonObject, JsonValue } from '../../../../common/value-objects/json-value';
import { DEFECT_REVIEW_STATUSES, DefectModelFinding, DefectModelMetadata, DefectModelStatus, DefectReview, DefectSourceSpan } from '../../domain/entities/defect-review';
import { DefectReviewRequestState } from '../../domain/value-objects/defect-review-request';

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown, max: number): value is string => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
const probability = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
const hash = (value: string): string => createHash('sha256').update(value).digest('hex');
const sha256 = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);

function limitations(value: unknown): string[] {
  if (!Array.isArray(value) || value.length > 24 || value.some((item) => !text(item, 4000))) throw new Error('Invalid limitations');
  return [...value] as string[];
}

/** Only finite, bounded, inert JSON statistics may accompany model provenance. */
function evaluation(value: unknown): JsonObject {
  if (!object(value)) throw new Error('Invalid evaluation statistics');
  let nodes = 0;
  function clone(item: unknown, depth: number): JsonValue {
    if (++nodes > 2000 || depth > 12) throw new Error('Excessive evaluation structure');
    if (item === null || typeof item === 'boolean' || (typeof item === 'number' && Number.isFinite(item))) return item;
    if (typeof item === 'string' && item.length <= 4000) return item;
    if (Array.isArray(item)) return item.map((child) => clone(child, depth + 1));
    if (object(item)) return Object.fromEntries(Object.entries(item).map(([key, child]) => [key, clone(child, depth + 1)]));
    throw new Error('Invalid evaluation value');
  }
  return clone(value, 0) as JsonObject;
}

function model(value: unknown): DefectModelMetadata | null {
  if (value === null) return null;
  if (!object(value) || !text(value.name, 200) || !sha256(value.sha256) || !sha256(value.datasetSha256)
    || value.trainingFamilyCount !== 6) throw new Error('Invalid model provenance');
  return { name: value.name, sha256: value.sha256, datasetSha256: value.datasetSha256, trainingFamilyCount: 6,
    ...(value.evaluation === undefined ? {} : { evaluation: evaluation(value.evaluation) }) };
}

function span(value: unknown, source: string): DefectSourceSpan | null {
  if (value === null) return null;
  if (!object(value) || !Number.isInteger(value.start) || !Number.isInteger(value.end)
    || (value.start as number) < 1 || (value.end as number) < (value.start as number)
    || (value.end as number) > source.split('\n').length) throw new Error('Invalid source span');
  return { start: value.start as number, end: value.end as number };
}
function excerpt(source: string, lines: DefectSourceSpan | null): string {
  return lines === null ? '' : source.split('\n').slice(lines.start - 1, lines.end).join('\n');
}
function invalid(cause: unknown): never {
  throw new InfrastructureException('The local defect engine result did not satisfy source and evidence invariants.', 'engine.invalid_result', { cause });
}

/** Validate the worker boundary before returning any model statement to HTTP clients. */
export function validatedDefectReview(raw: unknown, input: DefectReviewRequestState): DefectReview {
  try {
    if (!object(raw) || !DEFECT_REVIEW_STATUSES.includes(raw.status as DefectReview['status']) || raw.engineVersion !== 'paired-defect-v1'
      || raw.aiIsProof !== false || raw.counterexamplesExecuted !== false || !text(raw.summary, 4000)
      || !object(raw.sourceHashes) || raw.sourceHashes.cobol !== hash(input.cobolSource) || raw.sourceHashes.java !== hash(input.javaSource)
      || !object(raw.risk) || !probability(raw.risk.score) || !probability(raw.risk.threshold) || raw.risk.calibrated !== false
      || raw.risk.decision !== (raw.risk.score >= raw.risk.threshold ? 'REVIEW_REQUIRED' : 'NO_DEFECT_SIGNAL')
      || !Array.isArray(raw.findings) || raw.findings.length > 8 || (raw.status !== 'ANALYZED' && raw.findings.length !== 0)) {
      throw new Error('Invalid defect review envelope');
    }
    const metadata = model(raw.model);
    if (raw.status === 'ANALYZED' && metadata === null) throw new Error('Analyzed review requires model provenance');
    if (raw.status === 'NOT_CONFIGURED' && metadata !== null) throw new Error('Unconfigured engine cannot claim a configured model');
    const findings: DefectModelFinding[] = raw.findings.map((finding: unknown, index: number) => {
      if (!object(finding) || finding.findingId !== `F${index + 1}` || finding.evidenceStatus !== 'MODEL_HYPOTHESIS'
        || finding.category !== 'SEMANTIC_DIFFERENCE' || !text(finding.title, 200) || !text(finding.explanation, 4000)
        || typeof finding.suggestedFix !== 'string' || finding.suggestedFix.length > 4000 || !probability(finding.score)
        || !Array.isArray(finding.candidateInputs) || finding.candidateInputs.length !== 0) throw new Error('Invalid model hypothesis');
      const cobolLines = span(finding.cobolLines, input.cobolSource);
      const javaLines = span(finding.javaLines, input.javaSource);
      if ((cobolLines === null && javaLines === null) || finding.cobolExcerpt !== excerpt(input.cobolSource, cobolLines)
        || finding.javaExcerpt !== excerpt(input.javaSource, javaLines)) throw new Error('Hypothesis differs from submitted source');
      return { findingId: `F${index + 1}`, evidenceStatus: 'MODEL_HYPOTHESIS', title: finding.title, explanation: finding.explanation,
        suggestedFix: finding.suggestedFix, cobolLines, javaLines, cobolExcerpt: finding.cobolExcerpt as string,
        javaExcerpt: finding.javaExcerpt as string, score: finding.score, category: 'SEMANTIC_DIFFERENCE', candidateInputs: [] };
    });
    return { status: raw.status as DefectReview['status'], engineVersion: 'paired-defect-v1',
      sourceHashes: { cobol: raw.sourceHashes.cobol as string, java: raw.sourceHashes.java as string }, aiIsProof: false,
      counterexamplesExecuted: false, risk: { score: raw.risk.score, threshold: raw.risk.threshold, decision: raw.risk.decision as DefectReview['risk']['decision'],
        calibrated: false }, model: metadata, summary: raw.summary, limitations: limitations(raw.limitations), findings };
  } catch (cause) { return invalid(cause); }
}

export function validatedDefectModelStatus(raw: unknown): DefectModelStatus {
  try {
    if (!object(raw) || typeof raw.configured !== 'boolean') throw new Error('Invalid model status');
    const metadata = model(raw.model);
    if (raw.configured !== (metadata !== null)) throw new Error('Configured flag differs from model provenance');
    return { configured: raw.configured, model: metadata, limitations: limitations(raw.limitations) };
  } catch (cause) { return invalid(cause); }
}
