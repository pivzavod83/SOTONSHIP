import { createHash } from 'node:crypto';
import { InfrastructureException } from '../../../../common/exceptions/infrastructure.exception';
import { AI_DEFECT_CATEGORIES, AI_REVIEW_STATUSES, AiDefectFinding, AiReview, SourceLineSpan } from '../../domain/entities/ai-review';
import { AiReviewRequestState } from '../../domain/value-objects/ai-review-request';

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown, max: number): value is string => typeof value === 'string' && value.trim().length > 0 && value.length <= max;
const hash = (value: string): string => createHash('sha256').update(value).digest('hex');

function span(value: unknown, source: string): SourceLineSpan | null {
  if (value === null) return null;
  if (!object(value) || !Number.isInteger(value.start) || !Number.isInteger(value.end)
    || (value.start as number) < 1 || (value.end as number) < (value.start as number)
    || (value.end as number) > source.split('\n').length) throw new Error('Invalid source span');
  return { start: value.start as number, end: value.end as number };
}
function excerpt(source: string, lines: SourceLineSpan | null): string {
  return lines === null ? '' : source.split('\n').slice(lines.start - 1, lines.end).join('\n');
}
function validateInputJson(value: unknown): string {
  if (!text(value, 4000)) throw new Error('Invalid proposed input');
  const parsed: unknown = JSON.parse(value);
  if (!object(parsed)) throw new Error('Proposed input must be an object');
  let nodes = 0;
  function inspect(item: unknown, depth: number): void {
    if (++nodes > 1000 || depth > 20) throw new Error('Excessive proposed input structure');
    if (item === null || typeof item === 'boolean' || typeof item === 'string' || (typeof item === 'number' && Number.isFinite(item))) return;
    if (Array.isArray(item)) { item.forEach((child) => inspect(child, depth + 1)); return; }
    if (object(item)) { Object.values(item).forEach((child) => inspect(child, depth + 1)); return; }
    throw new Error('Non-finite proposed input');
  }
  inspect(parsed, 0);
  return value;
}

/** Whitelist subprocess fields, verify source anchors, and reject any proof claim. */
export function validatedAiReview(raw: unknown, input: AiReviewRequestState): AiReview {
  try {
    if (!object(raw) || !AI_REVIEW_STATUSES.includes(raw.status as AiReview['status']) || !text(raw.summary, 4000)
      || raw.aiIsProof !== false || raw.counterexamplesExecuted !== false || raw.promptVersion !== 'paired-defect-review-v1'
      || !object(raw.sourceHashes) || raw.sourceHashes.cobol !== hash(input.cobolSource) || raw.sourceHashes.java !== hash(input.javaSource)
      || !object(raw.provider) || raw.provider.protocol !== 'OPENAI_COMPATIBLE_CHAT'
      || (raw.provider.model !== null && !text(raw.provider.model, 200))
      || !Array.isArray(raw.limitations) || raw.limitations.length > 16 || raw.limitations.some((item) => !text(item, 2000))
      || !Array.isArray(raw.findings) || raw.findings.length > 8 || (raw.status !== 'ANALYZED' && raw.findings.length !== 0)) throw new Error('Invalid review envelope');
    const findings: AiDefectFinding[] = raw.findings.map((finding: unknown, index: number) => {
      if (!object(finding) || finding.findingId !== `F${index + 1}` || !text(finding.title, 160)
        || !AI_DEFECT_CATEGORIES.includes(finding.category as AiDefectFinding['category']) || !['LOW', 'MEDIUM', 'HIGH'].includes(finding.severity as string)
        || !text(finding.explanation, 4000) || typeof finding.suggestedFix !== 'string' || finding.suggestedFix.length > 4000 || finding.evidenceStatus !== 'AI_HYPOTHESIS'
        || !Array.isArray(finding.candidateInputs) || finding.candidateInputs.length > 3) throw new Error('Invalid finding');
      const cobolLines = span(finding.cobolLines, input.cobolSource);
      const javaLines = span(finding.javaLines, input.javaSource);
      if ((cobolLines === null && javaLines === null) || finding.cobolExcerpt !== excerpt(input.cobolSource, cobolLines)
        || finding.javaExcerpt !== excerpt(input.javaSource, javaLines)) throw new Error('Finding anchor differs from submitted source');
      return {
        findingId: `F${index + 1}`, title: finding.title, category: finding.category as AiDefectFinding['category'],
        severity: finding.severity as AiDefectFinding['severity'], explanation: finding.explanation, cobolLines, javaLines,
        cobolExcerpt: finding.cobolExcerpt as string, javaExcerpt: finding.javaExcerpt as string, suggestedFix: finding.suggestedFix,
        candidateInputs: finding.candidateInputs.map((candidate: unknown) => {
          if (!object(candidate) || !text(candidate.rationale, 1000) || candidate.status !== 'NOT_EXECUTED') throw new Error('Invalid candidate input');
          return { inputsJson: validateInputJson(candidate.inputsJson), rationale: candidate.rationale, status: 'NOT_EXECUTED' as const };
        }), evidenceStatus: 'AI_HYPOTHESIS',
      };
    });
    return {
      status: raw.status as AiReview['status'], summary: raw.summary, findings, limitations: [...raw.limitations] as string[],
      sourceHashes: { cobol: raw.sourceHashes.cobol as string, java: raw.sourceHashes.java as string },
      provider: { protocol: 'OPENAI_COMPATIBLE_CHAT', model: raw.provider.model as string | null },
      aiIsProof: false, promptVersion: 'paired-defect-review-v1', counterexamplesExecuted: false,
    };
  } catch (cause) {
    throw new InfrastructureException('The AI review engine result did not satisfy source and evidence invariants.', 'engine.invalid_result', { cause });
  }
}
