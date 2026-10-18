import type { VerificationCategory, VerificationResult } from './contracts';

export interface FileLabel { name: string; path: string; dirty: boolean; }
export interface PanelState {
  backendUrl: string; busy: boolean; message: string; category: VerificationCategory;
  files: { cobol?: FileLabel; java?: FileLabel; candidate?: FileLabel; };
  proofInputsText: string;
  result?: VerificationResult; candidateResult?: VerificationResult;
  resultStale: boolean; candidateStale: boolean; canApply: boolean; applied: boolean;
}
export type WorkbenchMessage =
  | { type: 'ready' | 'chooseCobol' | 'chooseJava' | 'chooseCandidate' | 'chooseContract' | 'demo' | 'verify' | 'verifyCandidate' | 'showDiff' | 'applyCandidate' | 'openCobol' | 'openJava' | 'openCandidate' | 'clearCandidate' | 'openSettings' | 'exportReport' }
  | { type: 'updateProofInputs' | 'setBackendUrl' | 'setCategory'; value: string; };
