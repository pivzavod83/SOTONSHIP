import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@mikro-orm/nestjs';
import { EntityRepository } from '@mikro-orm/postgresql';
import { IVerificationHistoryRepository } from '../../domain/repositories/verification-history.repository';
import { VerificationId } from '../../domain/value-objects/verification-id';
import { VerificationRevisionEntity } from '../../entities/verification-revision.entity';
import { VerificationRevisionMapper } from '../mappers/verification-revision.mapper';
import { VerificationRevision } from '../../domain/entities/verification-revision';
import { InfrastructureException } from '../../../../common/exceptions/infrastructure.exception';
@Injectable()
export class MikroOrmVerificationHistoryRepository implements IVerificationHistoryRepository {
  constructor(@InjectRepository(VerificationRevisionEntity) private readonly rows: EntityRepository<VerificationRevisionEntity>) {}
  async findByVerification(id: VerificationId): Promise<VerificationRevision[]> {
    try { return (await this.rows.find({ verificationId: id.value }, { orderBy: { version: 'asc' } })).map(VerificationRevisionMapper.toDomain); }
    catch (cause) { throw new InfrastructureException('Could not read revision history.', 'database.read_failed', { cause }); }
  }
}
