import { Body, Controller, HttpCode, Post } from '@nestjs/common';
import { QueryBus } from '@nestjs/cqrs';
import { ApiBadRequestResponse, ApiOkResponse, ApiOperation, ApiServiceUnavailableResponse, ApiTags } from '@nestjs/swagger';
import { ErrorRto } from '../../../../common/rto/error.rto';
import { MatchProgramsQuery } from '../../application/queries/match-programs.query';
import { MatchProgramsDto } from '../dto/match-programs.dto';
import { ProgramMatchesRto } from '../rto/program-matches.rto';

@ApiTags('Migration matching')
@Controller('matches')
export class MatchingController {
  constructor(private readonly queryBus: QueryBus) {}

  @Post()
  @HttpCode(200)
  @ApiOperation({ summary: 'Rank candidate Java programs using the paired-source GNN. Human confirmation and separate verification are required.' })
  @ApiOkResponse({ type: ProgramMatchesRto })
  @ApiBadRequestResponse({ type: ErrorRto })
  @ApiServiceUnavailableResponse({ type: ErrorRto })
  match(@Body() dto: MatchProgramsDto): Promise<ProgramMatchesRto> {
    return this.queryBus.execute(new MatchProgramsQuery(dto));
  }
}
