import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@mikro-orm/nestjs';
import { EntityManager, EntityRepository, LockMode } from '@mikro-orm/postgresql';
import { IVerificationRepository } from '../../domain/repositories/verification.repository';
import { VerificationRun } from '../../domain/entities/verification-run';
import { VerificationId } from '../../domain/value-objects/verification-id';
import { VerificationEntity } from '../../entities/verification.entity';
import { VerificationMapper } from '../mappers/verification.mapper';
import { InfrastructureException } from '../../../../common/exceptions/infrastructure.exception';
import { ApplicationException } from '../../../../common/exceptions/application.exception';

@Injectable()
export class MikroOrmVerificationRepository implements IVerificationRepository {
  constructor(@InjectRepository(VerificationEntity) private readonly repository: EntityRepository<VerificationEntity>,
    private readonly em: EntityManager) {}

  async findAll(): Promise<VerificationRun[]> {
    try {
      return (await this.repository.findAll({ orderBy: { createdAt: 'asc', moduleName: 'asc' } })).map(VerificationMapper.toDomain);
    } catch (cause) { throw new InfrastructureException('Could not read verification records.', 'database.read_failed', { cause }); }
  }
  async findById(id: VerificationId): Promise<VerificationRun | null> {
    try {
      const row = await this.repository.findOne({ id: id.value });
      return row ? VerificationMapper.toDomain(row) : null;
    } catch (cause) { throw new InfrastructureException('Could not read the verification.', 'database.read_failed', { cause }); }
  }
  async save(run: VerificationRun): Promise<VerificationRun> {
    try {
      const existing = await this.repository.findOne({ id: run.id.value });
      if (existing) await this.em.lock(existing, LockMode.OPTIMISTIC, run.toPrimitives().version);
      const row = VerificationMapper.toPersistence(run, existing ?? undefined);
      await this.em.persistAndFlush(row);
      return VerificationMapper.toDomain(row);
    } catch (cause) {
      if (cause instanceof Error && cause.name === 'OptimisticLockError') {
        throw new ApplicationException('This verification changed while it was being analysed; retry the request.', 'verification.conflict', 409);
      }
      throw new InfrastructureException('Could not save the verification.', 'database.write_failed', { cause });
    }
  }
}
