import { ApiProperty } from '@nestjs/swagger';
import { JsonObject } from '../../../../common/value-objects/json-value';
import { ProgramMatches } from '../../domain/entities/program-matches';

class RankedProgramCandidateRto {
  @ApiProperty() candidateId!: string;
  @ApiProperty() moduleName!: string;
  @ApiProperty() javaSourceSha256!: string;
  @ApiProperty({ minimum: 1 }) rank!: number;
  @ApiProperty({ minimum: -1, maximum: 1 }) similarity!: number;
}
class MatchingModelRto {
  @ApiProperty() id!: string;
  @ApiProperty() sha256!: string;
  @ApiProperty() trainingDataset!: string;
  @ApiProperty({ type: 'object', additionalProperties: true }) evaluation!: JsonObject;
}
class MatchingThresholdsRto {
  @ApiProperty() minimumSimilarity!: number;
  @ApiProperty() minimumMargin!: number;
}
export class ProgramMatchesRto {
  @ApiProperty({ enum: ['MATCH_SUGGESTED', 'REVIEW_REQUIRED'] }) status!: ProgramMatches['status'];
  @ApiProperty() reason!: string;
  @ApiProperty({ enum: [false], description: 'Matching never constitutes formal equivalence evidence.' }) matchingIsProof!: false;
  @ApiProperty({ enum: ['PROGRAM'] }) granularity!: 'PROGRAM';
  @ApiProperty({ type: MatchingModelRto }) model!: MatchingModelRto;
  @ApiProperty() cobolSourceSha256!: string;
  @ApiProperty({ type: [RankedProgramCandidateRto] }) candidates!: RankedProgramCandidateRto[];
  @ApiProperty({ type: MatchingThresholdsRto }) thresholds!: MatchingThresholdsRto;

  static fromDomain(matches: ProgramMatches): ProgramMatchesRto {
    return Object.assign(new ProgramMatchesRto(), {
      status: matches.status, reason: matches.reason, matchingIsProof: false as const, granularity: 'PROGRAM' as const,
      cobolSourceSha256: matches.cobolSourceSha256,
      model: Object.assign(new MatchingModelRto(), matches.model),
      candidates: matches.candidates.map((candidate) => Object.assign(new RankedProgramCandidateRto(), candidate)),
      thresholds: Object.assign(new MatchingThresholdsRto(), matches.thresholds),
    });
  }
}
