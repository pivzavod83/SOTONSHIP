import { randomUUID } from 'node:crypto';
import { VerificationRevision } from '../../domain/entities/verification-revision';
import { VerificationRun } from '../../domain/entities/verification-run';
import { VerificationRevisionEntity } from '../../entities/verification-revision.entity';
import { JsonObject } from '../../../../common/value-objects/json-value';
export class VerificationRevisionMapper {
  static toDomain(row: VerificationRevisionEntity): VerificationRevision {
    return new VerificationRevision(row.id, row.verificationId, row.version, row.recordedAt, structuredClone(row.snapshotJson));
  }
  static snapshot(run: VerificationRun): VerificationRevisionEntity {
    const state = run.toPrimitives();
    return Object.assign(new VerificationRevisionEntity(), { id: randomUUID(), verificationId: state.id, version: state.version,
      recordedAt: new Date(), snapshotJson: JSON.parse(JSON.stringify(state)) as JsonObject });
  }
}
