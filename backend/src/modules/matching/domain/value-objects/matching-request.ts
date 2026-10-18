import { DomainException } from '../../../../common/exceptions/domain.exception';

export type CobolSourceFormat = 'AUTO' | 'FREE' | 'FIXED';
export interface MatchingCandidate { candidateId: string; moduleName: string; javaSource: string; }
export interface MatchingRequestInput {
  cobolSource: string;
  cobolSourceFormat?: CobolSourceFormat;
  candidates: MatchingCandidate[];
  topK?: number;
}
export interface MatchingRequestState {
  cobolSource: string;
  cobolSourceFormat: CobolSourceFormat;
  candidates: MatchingCandidate[];
  topK: number;
}

/** A bounded, whole-program discovery request; matching never grants proof authority. */
export class MatchingRequest {
  private readonly state: MatchingRequestState;

  constructor(input: MatchingRequestInput) {
    const invalid = (message: string): never => { throw new DomainException(message, 'matching.invalid_request'); };
    const validSource = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0
      && value.length <= 100_000 && value.split(/\r\n|\r|\n/).length <= 1500 && !value.includes('\0');
    if (!validSource(input.cobolSource)) invalid('COBOL source must contain 1–100000 characters and at most 1500 lines.');
    const format = input.cobolSourceFormat ?? 'AUTO';
    if (!['AUTO', 'FREE', 'FIXED'].includes(format)) invalid('COBOL source format is invalid.');
    if (!Array.isArray(input.candidates) || input.candidates.length < 1 || input.candidates.length > 20) {
      invalid('Supply between 1 and 20 Java candidates.');
    }
    const ids = new Set<string>();
    for (const candidate of input.candidates) {
      if (!candidate || typeof candidate.candidateId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$/.test(candidate.candidateId)) {
        invalid('Candidate identifiers must be 1–80 ASCII letters, digits, dots, underscores, colons or hyphens.');
      }
      if (ids.has(candidate.candidateId)) invalid('Candidate identifiers must be unique.');
      ids.add(candidate.candidateId);
      if (typeof candidate.moduleName !== 'string' || !candidate.moduleName.trim() || candidate.moduleName.length > 160
        || /[\x00-\x1f/\\]/.test(candidate.moduleName)) invalid('Candidate module names must be nonempty names without paths or control characters.');
      if (!validSource(candidate.javaSource)) invalid('Each Java source must contain 1–100000 characters and at most 1500 lines.');
    }
    const topK = input.topK ?? 5;
    if (!Number.isInteger(topK) || topK < 1 || topK > 20) invalid('topK must be an integer between 1 and 20.');
    this.state = {
      cobolSource: input.cobolSource, cobolSourceFormat: format,
      candidates: input.candidates.map(({ candidateId, moduleName, javaSource }) => ({ candidateId, moduleName, javaSource })), topK,
    };
    if (Buffer.byteLength(JSON.stringify(this.state), 'utf8') > 2 * 1024 * 1024) invalid('The matching payload exceeds 2 MiB.');
  }

  toPrimitives(): MatchingRequestState {
    return { ...this.state, candidates: this.state.candidates.map((candidate) => ({ ...candidate })) };
  }
}
