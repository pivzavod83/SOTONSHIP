export const AI_REVIEW_STATUSES = ['ANALYZED', 'NOT_CONFIGURED', 'PROVIDER_ERROR', 'INVALID_MODEL_OUTPUT', 'REFUSED'] as const;
export const AI_DEFECT_CATEGORIES = ['ARITHMETIC', 'ROUNDING', 'CONTROL_FLOW', 'INDEXING', 'DATA_REPRESENTATION', 'STATE', 'STRING_HANDLING', 'OTHER'] as const;
export interface SourceLineSpan { start: number; end: number; }
export interface CandidateDefectInput { inputsJson: string; rationale: string; status: 'NOT_EXECUTED'; }
export interface AiDefectFinding {
  findingId: string;
  title: string;
  category: typeof AI_DEFECT_CATEGORIES[number];
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  explanation: string;
  cobolLines: SourceLineSpan | null;
  javaLines: SourceLineSpan | null;
  cobolExcerpt: string;
  javaExcerpt: string;
  suggestedFix: string;
  candidateInputs: CandidateDefectInput[];
  evidenceStatus: 'AI_HYPOTHESIS';
}

/** A model review is advisory evidence and cannot change formal proof authority. */
export interface AiReview {
  status: typeof AI_REVIEW_STATUSES[number];
  summary: string;
  findings: AiDefectFinding[];
  limitations: string[];
  sourceHashes: { cobol: string; java: string };
  provider: { protocol: 'OPENAI_COMPATIBLE_CHAT'; model: string | null };
  aiIsProof: false;
  promptVersion: 'paired-defect-review-v1';
  counterexamplesExecuted: false;
}
