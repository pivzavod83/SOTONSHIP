import { JsonObject } from '../../../../common/value-objects/json-value';

export const DEFECT_REVIEW_STATUSES = ['ANALYZED', 'NOT_CONFIGURED', 'UNSUPPORTED'] as const;
export interface DefectSourceSpan { start: number; end: number; }
export interface DefectModelMetadata {
  name: string;
  sha256: string;
  datasetSha256: string;
  trainingFamilyCount: 6;
  evaluation?: JsonObject;
}
export interface DefectModelFinding {
  findingId: string;
  evidenceStatus: 'MODEL_HYPOTHESIS';
  title: string;
  explanation: string;
  suggestedFix: string;
  cobolLines: DefectSourceSpan | null;
  javaLines: DefectSourceSpan | null;
  cobolExcerpt: string;
  javaExcerpt: string;
  score: number;
  category: 'SEMANTIC_DIFFERENCE';
  candidateInputs: [];
}

/** A local model's source-bound hypotheses have no authority over formal verification. */
export interface DefectReview {
  status: typeof DEFECT_REVIEW_STATUSES[number];
  engineVersion: 'paired-defect-v1';
  sourceHashes: { cobol: string; java: string };
  aiIsProof: false;
  counterexamplesExecuted: false;
  risk: { score: number; threshold: number; decision: 'REVIEW_REQUIRED' | 'NO_DEFECT_SIGNAL'; calibrated: false };
  model: DefectModelMetadata | null;
  summary: string;
  limitations: string[];
  findings: DefectModelFinding[];
}
export interface DefectModelStatus { configured: boolean; model: DefectModelMetadata | null; limitations: string[]; }
