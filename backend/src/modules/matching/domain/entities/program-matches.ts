import { JsonObject } from '../../../../common/value-objects/json-value';

export interface RankedProgramCandidate {
  candidateId: string;
  moduleName: string;
  javaSourceSha256: string;
  rank: number;
  similarity: number;
}

/** Suggestions assist human discovery. They are neither equivalence nor repair evidence. */
export interface ProgramMatches {
  status: 'MATCH_SUGGESTED' | 'REVIEW_REQUIRED';
  reason: string;
  matchingIsProof: false;
  granularity: 'PROGRAM';
  model: { id: string; sha256: string; trainingDataset: string; evaluation: JsonObject };
  cobolSourceSha256: string;
  candidates: RankedProgramCandidate[];
  thresholds: { minimumSimilarity: number; minimumMargin: number };
}
