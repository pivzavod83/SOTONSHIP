import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { MatchingRequest } from '../../../domain/value-objects/matching-request';
import { ProgramMatchesRto } from '../../../presentation/rto/program-matches.rto';
import { IProgramMatchingEngine, PROGRAM_MATCHING_ENGINE } from '../../ports/program-matching-engine';
import { validatedProgramMatches } from '../../services/validated-program-matches';
import { MatchProgramsQuery } from '../match-programs.query';

@QueryHandler(MatchProgramsQuery)
export class MatchProgramsHandler implements IQueryHandler<MatchProgramsQuery> {
  constructor(@Inject(PROGRAM_MATCHING_ENGINE) private readonly engine: IProgramMatchingEngine) {}

  async execute(query: MatchProgramsQuery): Promise<ProgramMatchesRto> {
    const input = new MatchingRequest(query.input).toPrimitives();
    const raw = await this.engine.match({ ...input, topK: input.candidates.length });
    const matches = validatedProgramMatches(raw, input);
    return ProgramMatchesRto.fromDomain({ ...matches, candidates: matches.candidates.slice(0, input.topK) });
  }
}
