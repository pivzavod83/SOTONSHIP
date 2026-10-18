import { createHash } from 'node:crypto';
import { InfrastructureException } from '../../../../common/exceptions/infrastructure.exception';
import { JsonObject, JsonValue } from '../../../../common/value-objects/json-value';
import { ProgramMatches, RankedProgramCandidate } from '../../domain/entities/program-matches';
import { MatchingRequestState } from '../../domain/value-objects/matching-request';

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function text(value: unknown, max: number): value is string { return typeof value === 'string' && value.trim().length > 0 && value.length <= max; }
function finite(value: unknown, min: number, max: number): value is number { return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max; }
const hash = (source: string): string => createHash('sha256').update(source).digest('hex');
const sha256 = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);

function evaluation(value: unknown): JsonObject {
  let nodes = 0;
  function copy(item: unknown, depth: number): JsonValue {
    if (++nodes > 2000 || depth > 8) throw new Error('Oversized model evaluation');
    if (item === null || typeof item === 'boolean') return item;
    if (typeof item === 'number' && Number.isFinite(item)) return item;
    if (typeof item === 'string' && item.length <= 2000) return item;
    if (Array.isArray(item) && item.length <= 200) return item.map((child) => copy(child, depth + 1));
    if (object(item) && Object.keys(item).length <= 100) {
      const output: JsonObject = {};
      for (const [key, child] of Object.entries(item)) {
        if (key.length > 160 || ['__proto__', 'constructor', 'prototype'].includes(key)) throw new Error('Invalid evaluation key');
        output[key] = copy(child, depth + 1);
      }
      return output;
    }
    throw new Error('Invalid evaluation JSON');
  }
  if (!object(value) || Object.keys(value).length === 0) throw new Error('Missing model evaluation');
  const result = copy(value, 0) as JsonObject;
  if (Buffer.byteLength(JSON.stringify(result), 'utf8') > 32_768) throw new Error('Oversized model evaluation');
  return result;
}

/** Validate untrusted subprocess output, bind it to exact sources, and whitelist all HTTP fields. */
export function validatedProgramMatches(raw: unknown, input: MatchingRequestState): ProgramMatches {
  try {
    if (!object(raw) || (raw.status !== 'MATCH_SUGGESTED' && raw.status !== 'REVIEW_REQUIRED')
      || !text(raw.reason, 2000) || raw.matchingIsProof !== false || raw.granularity !== 'PROGRAM'
      || raw.cobolSourceSha256 !== hash(input.cobolSource) || !object(raw.model) || !text(raw.model.id, 160)
      || !sha256(raw.model.sha256) || !text(raw.model.trainingDataset, 1000) || !object(raw.thresholds)
      || !finite(raw.thresholds.minimumSimilarity, -1, 1) || !finite(raw.thresholds.minimumMargin, 0, 2)
      || !Array.isArray(raw.candidates) || raw.candidates.length !== input.candidates.length) throw new Error('Invalid matching envelope');
    const seen = new Set<string>();
    const candidates: RankedProgramCandidate[] = raw.candidates.map((candidate: unknown, index: number) => {
      if (!object(candidate) || !text(candidate.candidateId, 80) || seen.has(candidate.candidateId)
        || candidate.rank !== index + 1 || !finite(candidate.similarity, -1, 1)) throw new Error('Invalid candidate rank');
      const submitted = input.candidates.find((entry) => entry.candidateId === candidate.candidateId);
      if (!submitted || candidate.moduleName !== submitted.moduleName || candidate.javaSourceSha256 !== hash(submitted.javaSource)) throw new Error('Candidate source mismatch');
      seen.add(candidate.candidateId);
      return { candidateId: submitted.candidateId, moduleName: submitted.moduleName,
        javaSourceSha256: candidate.javaSourceSha256 as string, rank: candidate.rank as number, similarity: candidate.similarity };
    });
    if (candidates.some((candidate, index) => index > 0 && candidate.similarity > candidates[index - 1].similarity)) throw new Error('Candidates are not sorted');
    if (raw.status === 'MATCH_SUGGESTED' && (candidates.length < 2
      || candidates[0].similarity < raw.thresholds.minimumSimilarity
      || candidates[0].similarity - candidates[1].similarity < raw.thresholds.minimumMargin)) throw new Error('Suggestion does not meet thresholds');
    return {
      status: raw.status as ProgramMatches['status'], reason: raw.reason, matchingIsProof: false, granularity: 'PROGRAM',
      model: { id: raw.model.id, sha256: raw.model.sha256, trainingDataset: raw.model.trainingDataset, evaluation: evaluation(raw.model.evaluation) },
      cobolSourceSha256: raw.cobolSourceSha256 as string, candidates,
      thresholds: { minimumSimilarity: raw.thresholds.minimumSimilarity, minimumMargin: raw.thresholds.minimumMargin },
    };
  } catch (cause) {
    throw new InfrastructureException('The matching engine result did not satisfy source and ranking invariants.', 'engine.invalid_result', { cause });
  }
}
