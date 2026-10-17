import { Inject } from '@nestjs/common';
import { IQueryHandler, QueryHandler } from '@nestjs/cqrs';
import { FX_RATE_REPOSITORY, IReferenceFxRateRepository } from '../../../domain/repositories/reference-fx-rate.repository';
import { ReferenceFxRateRto } from '../../../presentation/rto/reference-fx-rate.rto';
import { GetReferenceFxRatesQuery } from '../get-reference-fx-rates.query';

@QueryHandler(GetReferenceFxRatesQuery)
export class GetReferenceFxRatesHandler implements IQueryHandler<GetReferenceFxRatesQuery> {
  constructor(@Inject(FX_RATE_REPOSITORY) private readonly rates: IReferenceFxRateRepository) {}
  async execute(): Promise<ReferenceFxRateRto[]> { return (await this.rates.findAll()).map(ReferenceFxRateRto.fromDomain); }
}
