import { Entity, PrimaryKey, Property, Unique } from '@mikro-orm/core';
import { JsonObject } from '../../../common/value-objects/json-value';
@Entity({ tableName: 'verification_revisions' })
@Unique({ name: 'verification_revisions_version_unique', properties: ['verificationId', 'version'] })
export class VerificationRevisionEntity {
  @PrimaryKey({ type: 'uuid' }) id!: string;
  @Property({ type: 'uuid' }) verificationId!: string;
  @Property() version!: number;
  @Property() recordedAt!: Date;
  @Property({ type: 'json' }) snapshotJson!: JsonObject;
}
