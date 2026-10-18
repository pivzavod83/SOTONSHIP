import type { VerificationCategory, VerificationResult } from './contracts';
import type { MatchingResult, MatchingSourceFormat } from './matching-contracts';
import type { AiReviewResult, AiReviewSourceFormat } from './ai-review-contracts';

export interface FileLabel { name: string; path: string; dirty: boolean; }
export interface PanelState {
  backendUrl: string; busy: boolean; message: string; category: VerificationCategory;
  files: { cobol?: FileLabel; java?: FileLabel; candidate?: FileLabel; };
  proofInputsText: string;
  result?: VerificationResult; candidateResult?: VerificationResult;
  resultStale: boolean; candidateStale: boolean; canApply: boolean; applied: boolean;
  matchingFiles: { candidateId: string; file: FileLabel }[];
  matchingSourceFormat: MatchingSourceFormat;
  matchingResult?: MatchingResult; matchingStale: boolean; confirmedMatchId?: string;
  aiReviewResult?: AiReviewResult; aiReviewStale: boolean;
  aiReviewSourceFormat: AiReviewSourceFormat; aiReviewContext: string;
}
export type WorkbenchMessage =
  | { type: 'ready' | 'chooseCobol' | 'chooseJava' | 'chooseCandidate' | 'chooseMatchingFiles' | 'matchPrograms' | 'analyzePairWithAi' | 'chooseContract' | 'demo' | 'verify' | 'verifyCandidate' | 'showDiff' | 'applyCandidate' | 'openCobol' | 'openJava' | 'openCandidate' | 'clearCandidate' | 'openSettings' | 'exportReport' }
  | { type: 'updateProofInputs' | 'setBackendUrl' | 'setCategory' | 'setMatchingSourceFormat' | 'setAiReviewSourceFormat' | 'updateAiReviewContext' | 'confirmMatch'; value: string; };
