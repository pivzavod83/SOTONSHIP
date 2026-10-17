import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@mikro-orm/nestjs';
import { EntityRepository } from '@mikro-orm/postgresql';
import { IReferenceFxRateRepository } from '../../domain/repositories/reference-fx-rate.repository';
import { ReferenceFxRate } from '../../domain/entities/reference-fx-rate';
import { ReferenceFxRateEntity } from '../../entities/reference-fx-rate.entity';
import { ReferenceFxRateMapper } from '../mappers/reference-fx-rate.mapper';
import { InfrastructureException } from '../../../../common/exceptions/infrastructure.exception';

@Injectable()
export class MikroOrmReferenceFxRateRepository implements IReferenceFxRateRepository {
  constructor(@InjectRepository(ReferenceFxRateEntity) private readonly repository: EntityRepository<ReferenceFxRateEntity>) {}
  async findAll(): Promise<ReferenceFxRate[]> {
    try {
      return (await this.repository.findAll({ orderBy: { currencyPair: 'asc', collectedDate: 'desc' } })).map(ReferenceFxRateMapper.toDomain);
    } catch (cause) { throw new InfrastructureException('Could not read reference FX rates.', 'database.read_failed', { cause }); }
  }
}
