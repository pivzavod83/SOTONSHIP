import { createHash } from 'node:crypto';
import { validateSource } from './contracts';

export type AiReviewSourceFormat = 'AUTO' | 'FREE' | 'FIXED';
export interface AiReviewRequest {
  moduleName: string; cobolSource: string; javaSource: string;
  cobolSourceFormat: AiReviewSourceFormat; analysisContext?: string;
}
export interface AiReviewSpan { start: number; end: number; }
export interface AiReviewFinding {
  findingId: string; title: string;
  category: 'ARITHMETIC' | 'ROUNDING' | 'CONTROL_FLOW' | 'INDEXING' | 'DATA_REPRESENTATION' | 'STATE' | 'STRING_HANDLING' | 'OTHER';
  severity: 'LOW' | 'MEDIUM' | 'HIGH'; explanation: string;
  cobolLines: AiReviewSpan | null; javaLines: AiReviewSpan | null;
  cobolExcerpt: string; javaExcerpt: string; suggestedFix: string;
  candidateInputs: { inputsJson: string; rationale: string; status: 'NOT_EXECUTED' }[];
  evidenceStatus: 'AI_HYPOTHESIS';
}
export interface AiReviewResult {
  status: 'ANALYZED' | 'NOT_CONFIGURED' | 'PROVIDER_ERROR' | 'INVALID_MODEL_OUTPUT' | 'REFUSED';
  summary: string; findings: AiReviewFinding[]; limitations: string[];
  sourceHashes: { cobol: string; java: string };
  provider: { protocol: 'OPENAI_COMPATIBLE_CHAT'; model: string | null };
  aiIsProof: false; promptVersion: 'paired-defect-review-v1'; counterexamplesExecuted: false;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be a JSON object.`);
  return value as Record<string, unknown>;
}
function keys(value: Record<string, unknown>, expected: readonly string[], label: string): void {
  if (Object.keys(value).length !== expected.length || Object.keys(value).some(key => !expected.includes(key))) throw new Error(`${label} has unexpected fields.`);
}
function text(value: unknown, maximum: number, label: string, empty = false): string {
  if (typeof value !== 'string' || (!empty && !value.trim()) || value.length > maximum || value.includes('\0')) throw new Error(`${label} is invalid or exceeds its text limit.`);
  wellFormedUnicode(value, label);
  return value;
}
function wellFormedUnicode(value: string, label: string): void {
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(++index);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error(`${label} contains malformed Unicode.`);
    } else if (code >= 0xdc00 && code <= 0xdfff) throw new Error(`${label} contains malformed Unicode.`);
  }
}
export function aiSourceHash(source: string): string { return createHash('sha256').update(source, 'utf8').digest('hex'); }

export function validateAiReviewRequest(value: AiReviewRequest): AiReviewRequest {
  const input = object(value, 'AI review request');
  const expected = ['moduleName', 'cobolSource', 'javaSource', 'cobolSourceFormat', ...(input.analysisContext !== undefined ? ['analysisContext'] : [])];
  keys(input, expected, 'AI review request');
  text(value.moduleName, 160, 'Module name');
  if (/[\x00-\x1f\x7f/\\]/u.test(value.moduleName)) throw new Error('Module name must be a name without control characters or directory separators.');
  validateSource(value.cobolSource, 'COBOL source'); validateSource(value.javaSource, 'Java source');
  wellFormedUnicode(value.cobolSource, 'COBOL source'); wellFormedUnicode(value.javaSource, 'Java source');
  if (value.cobolSource.split('\n').length > 1500 || value.javaSource.split('\n').length > 1500) throw new Error('AI review sources must contain at most 1500 raw lines, including a trailing empty line.');
  if (!['AUTO', 'FREE', 'FIXED'].includes(value.cobolSourceFormat)) throw new Error('Unsupported AI review source format.');
  if (value.analysisContext !== undefined) text(value.analysisContext, 8000, 'AI analysis context', true);
  return { moduleName: value.moduleName, cobolSource: value.cobolSource, javaSource: value.javaSource, cobolSourceFormat: value.cobolSourceFormat,
    ...(value.analysisContext !== undefined ? { analysisContext: value.analysisContext } : {}) };
}

function span(value: unknown, source: string, excerpt: unknown, label: string): AiReviewSpan | null {
  if (value === null) { if (excerpt !== '') throw new Error(`${label} without a span must have an empty excerpt.`); return null; }
  const bounds = object(value, label); keys(bounds, ['start', 'end'], label);
  const lines = source.split('\n');
  if (typeof bounds.start !== 'number' || typeof bounds.end !== 'number' || !Number.isSafeInteger(bounds.start) || !Number.isSafeInteger(bounds.end)
    || bounds.start < 1 || bounds.end < bounds.start || bounds.end > lines.length) throw new Error(`${label} is outside the submitted source.`);
  if (excerpt !== lines.slice(bounds.start - 1, bounds.end).join('\n')) throw new Error(`${label} excerpt does not match the exact submitted source.`);
  return { start: bounds.start, end: bounds.end };
}
function finiteJson(value: unknown, depth = 0): boolean {
  if (depth > 50) return false;
  if (typeof value === 'number') return Number.isFinite(value);
  return !value || typeof value !== 'object' || Object.values(value).every(item => finiteJson(item, depth + 1));
}
export function parseAiReviewResult(value: unknown, request: AiReviewRequest): AiReviewResult {
  validateAiReviewRequest(request);
  const result = object(value, 'AI review');
  keys(result, ['status', 'summary', 'findings', 'limitations', 'sourceHashes', 'provider', 'aiIsProof', 'promptVersion', 'counterexamplesExecuted'], 'AI review');
  if (typeof result.status !== 'string' || !['ANALYZED', 'NOT_CONFIGURED', 'PROVIDER_ERROR', 'INVALID_MODEL_OUTPUT', 'REFUSED'].includes(result.status)) throw new Error('Unsupported AI review status.');
  if (result.aiIsProof !== false || result.counterexamplesExecuted !== false || result.promptVersion !== 'paired-defect-review-v1') throw new Error('AI review cannot claim proof or executed counterexamples.');
  text(result.summary, 8000, 'AI review summary');
  const hashes = object(result.sourceHashes, 'AI source hashes'); keys(hashes, ['cobol', 'java'], 'AI source hashes');
  if (hashes.cobol !== aiSourceHash(request.cobolSource) || hashes.java !== aiSourceHash(request.javaSource)) throw new Error('AI review does not refer to the exact submitted source pair.');
  const provider = object(result.provider, 'AI provider'); keys(provider, ['protocol', 'model'], 'AI provider');
  if (provider.protocol !== 'OPENAI_COMPATIBLE_CHAT') throw new Error('Unsupported AI provider protocol.');
  if (provider.model !== null) text(provider.model, 300, 'AI model');
  if (!Array.isArray(result.limitations) || result.limitations.length > 20) throw new Error('AI review limitations are invalid.');
  result.limitations.forEach(item => text(item, 4000, 'AI limitation'));
  if (!Array.isArray(result.findings) || result.findings.length > 8 || (result.status !== 'ANALYZED' && result.findings.length)) throw new Error('AI review findings are invalid for this status.');
  result.findings.forEach((raw, index) => {
    const finding = object(raw, 'AI finding');
    keys(finding, ['findingId', 'title', 'category', 'severity', 'explanation', 'cobolLines', 'javaLines', 'cobolExcerpt', 'javaExcerpt', 'suggestedFix', 'candidateInputs', 'evidenceStatus'], 'AI finding');
    if (finding.findingId !== `F${index + 1}` || finding.evidenceStatus !== 'AI_HYPOTHESIS') throw new Error('AI findings must be sequential hypotheses.');
    text(finding.title, 160, 'AI finding title'); text(finding.explanation, 4000, 'AI explanation'); text(finding.suggestedFix, 4000, 'Suggested correction', true);
    if (typeof finding.category !== 'string' || typeof finding.severity !== 'string'
      || !['ARITHMETIC', 'ROUNDING', 'CONTROL_FLOW', 'INDEXING', 'DATA_REPRESENTATION', 'STATE', 'STRING_HANDLING', 'OTHER'].includes(finding.category)
      || !['LOW', 'MEDIUM', 'HIGH'].includes(finding.severity)) throw new Error('AI finding category or severity is invalid.');
    const cobol = span(finding.cobolLines, request.cobolSource, finding.cobolExcerpt, 'COBOL span');
    const java = span(finding.javaLines, request.javaSource, finding.javaExcerpt, 'Java span');
    if (!cobol && !java) throw new Error('An AI finding requires at least one source span.');
    if (!Array.isArray(finding.candidateInputs) || finding.candidateInputs.length > 3) throw new Error('AI candidate inputs are invalid.');
    finding.candidateInputs.forEach(rawInput => {
      const input = object(rawInput, 'AI candidate input'); keys(input, ['inputsJson', 'rationale', 'status'], 'AI candidate input');
      if (input.status !== 'NOT_EXECUTED') throw new Error('AI candidate inputs must remain unexecuted.');
      const json = text(input.inputsJson, 4000, 'AI input JSON'); text(input.rationale, 1000, 'AI input rationale');
      let parsed: unknown; try { parsed = JSON.parse(json); } catch { throw new Error('AI candidate inputs must contain valid JSON.'); }
      object(parsed, 'AI candidate input JSON'); if (!finiteJson(parsed)) throw new Error('AI candidate input JSON must be finite and bounded in depth.');
    });
  });
  return structuredClone(result) as unknown as AiReviewResult;
}

/** Kept independent of VS Code for deterministic cancellation/staleness tests. */
export interface AiReviewBinding {
  cobolUri: string; javaUri: string; cobolVersion: number; javaVersion: number;
  backendUrl: string; sourceFormat: AiReviewSourceFormat; analysisContext: string;
  cobolHash: string; javaHash: string; generation: number;
}
export function sameAiReviewBinding(expected: AiReviewBinding, current: AiReviewBinding): boolean {
  return (Object.keys(expected) as (keyof AiReviewBinding)[]).every(key => expected[key] === current[key]);
}
