import { MatchingRequestState } from '../../domain/value-objects/matching-request';

export const PROGRAM_MATCHING_ENGINE = 'IProgramMatchingEngine';
export interface IProgramMatchingEngine {
  /** Full candidate list is requested so confidence can be checked before UI truncation. */
  match(input: MatchingRequestState): Promise<unknown>;
}
