import { MatchingRequestInput } from '../../domain/value-objects/matching-request';

export class MatchProgramsQuery {
  constructor(readonly input: MatchingRequestInput) {}
}
