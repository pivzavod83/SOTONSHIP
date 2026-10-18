import { createHash } from 'node:crypto';
import { validateSource } from './contracts';

export type MatchingSourceFormat = 'AUTO' | 'FREE' | 'FIXED';
export interface MatchingRequest {
  cobolSource: string; cobolSourceFormat?: MatchingSourceFormat;
  candidates: { candidateId: string; moduleName: string; javaSource: string }[];
  topK?: number;
}
export interface MatchingResult {
  status: 'MATCH_SUGGESTED' | 'REVIEW_REQUIRED'; reason: string;
  matchingIsProof: false; granularity: 'PROGRAM';
  model: { id: string; sha256: string; trainingDataset: string; evaluation: Record<string, unknown> };
  cobolSourceSha256: string;
  candidates: { candidateId: string; moduleName: string; javaSourceSha256: string; rank: number; similarity: number }[];
  thresholds: { minimumSimilarity: number; minimumMargin: number };
}
const hash = (source: string) => createHash('sha256').update(source, 'utf8').digest('hex');
function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object.`);
  return value as Record<string, unknown>;
}
function text(value: unknown, label: string, max: number): string {
  if (typeof value !== 'string' || !value.trim() || value.length > max || /[\x00-\x1f\x7f]/u.test(value)) throw new Error(`${label} is invalid.`);
  return value;
}
function number(value: unknown, label: string, minimum: number, maximum: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) throw new Error(`${label} is invalid.`);
  return value;
}
export function validateMatchingRequest(request: MatchingRequest): MatchingRequest {
  validateSource(request.cobolSource, 'COBOL source');
  if (request.cobolSourceFormat !== undefined && !['AUTO', 'FREE', 'FIXED'].includes(request.cobolSourceFormat)) throw new Error('Matching source format must be AUTO, FREE or FIXED.');
  if (!Array.isArray(request.candidates) || request.candidates.length < 1 || request.candidates.length > 20) throw new Error('Choose between 1 and 20 Java candidates.');
  const ids = new Set<string>();
  const candidates = request.candidates.map(candidate => {
    if (!candidate || typeof candidate.candidateId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/u.test(candidate.candidateId) || ids.has(candidate.candidateId)) throw new Error('Matching candidate IDs must be valid and unique.');
    ids.add(candidate.candidateId);
    text(candidate.moduleName, 'Candidate module name', 160);
    if (/[\/\\]/u.test(candidate.moduleName)) throw new Error('Candidate module name must not contain directory separators.');
    validateSource(candidate.javaSource, 'Candidate Java source');
    return { candidateId: candidate.candidateId, moduleName: candidate.moduleName, javaSource: candidate.javaSource };
  });
  if (request.topK !== undefined && (!Number.isSafeInteger(request.topK) || request.topK < 1 || request.topK > candidates.length)) throw new Error('topK must be between 1 and the candidate count.');
  return { cobolSource: request.cobolSource, ...(request.cobolSourceFormat ? { cobolSourceFormat: request.cobolSourceFormat } : {}), candidates,
    ...(request.topK !== undefined ? { topK: request.topK } : {}) };
}

/** Matching is an advisory ranking, never proof or a calibrated confidence percentage. */
export function parseMatchingResult(value: unknown, request: MatchingRequest): MatchingResult {
  const result = record(value, 'Matching response');
  if (!['MATCH_SUGGESTED', 'REVIEW_REQUIRED'].includes(result.status as string) || result.matchingIsProof !== false || result.granularity !== 'PROGRAM') throw new Error('The backend must return an advisory whole-program match, not proof.');
  text(result.reason, 'Matching reason', 5000);
  if (result.cobolSourceSha256 !== hash(request.cobolSource)) throw new Error('The matching result is not bound to the submitted COBOL source.');
  const model = record(result.model, 'Matching model');
  text(model.id, 'Model identity', 300);
  if (typeof model.sha256 !== 'string' || !/^[a-f0-9]{64}$/u.test(model.sha256)) throw new Error('Matching model SHA-256 is missing or invalid.');
  text(model.trainingDataset, 'Training dataset', 1000);
  record(model.evaluation, 'Model evaluation');
  const thresholds = record(result.thresholds, 'Matching thresholds');
  number(thresholds.minimumSimilarity, 'Minimum similarity', -1, 1);
  number(thresholds.minimumMargin, 'Minimum margin', 0, 2);
  if (!Array.isArray(result.candidates) || result.candidates.length !== (request.topK ?? Math.min(5, request.candidates.length))) throw new Error('The matching response has an unexpected number of candidates.');
  const seen = new Set<string>();
  let previous = Infinity;
  result.candidates.forEach((raw, index) => {
    const candidate = record(raw, 'Ranked candidate');
    const requested = request.candidates.find(item => item.candidateId === candidate.candidateId);
    if (!requested || seen.has(requested.candidateId) || candidate.moduleName !== requested.moduleName || candidate.javaSourceSha256 !== hash(requested.javaSource)) throw new Error('A matching candidate does not refer to the submitted Java source and identity.');
    seen.add(requested.candidateId);
    const similarity = number(candidate.similarity, 'Cosine similarity', -1, 1);
    if (candidate.rank !== index + 1 || similarity > previous + 1e-12) throw new Error('The matching candidates have inconsistent ranks or similarities.');
    previous = similarity;
  });
  return result as unknown as MatchingResult;
}
