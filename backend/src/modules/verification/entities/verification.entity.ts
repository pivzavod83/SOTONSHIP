import { Entity, Enum, PrimaryKey, Property } from '@mikro-orm/core';
import { VerificationCategory } from '../domain/enums/verification-category.enum';
import { FormalProofStatusValue } from '../domain/enums/formal-proof-status.enum';
import { JsonObject, JsonValue } from '../../../common/value-objects/json-value';

@Entity({ tableName: 'verifications' })
export class VerificationEntity {
  @PrimaryKey({ type: 'uuid' }) id!: string;
  @Property({ length: 160 }) moduleName!: string;
  @Enum(() => VerificationCategory) category!: VerificationCategory;
  @Property({ type: 'text' }) cobolSource!: string;
  @Property({ type: 'text' }) javaSource!: string;
  @Property({ type: 'text' }) patchedJavaSource!: string;
  @Property({ type: 'double' }) gnnAlignmentScore!: number;
  @Property({ type: 'double' }) gnnBugRiskScore!: number;
  @Property({ type: 'double' }) baselineAlignmentScore!: number;
  @Property() baselineCaughtBug!: boolean;
  @Enum(() => FormalProofStatusValue) formalProofStatus!: FormalProofStatusValue;
  @Property() bugCategory!: string;
  @Property({ type: 'text' }) fStringSummary!: string;
  @Property({ type: 'json' }) cpgGraphJson!: JsonObject;
  @Property({ type: 'json' }) counterexamplesJson!: JsonValue[];
  @Property() isFailureLimitCase!: boolean;
  @Property({ type: 'json' }) proofScope!: JsonObject;
  @Property({ type: 'json' }) provenanceJson!: JsonObject;
  @Property() createdAt!: Date;
  @Property({ onUpdate: () => new Date() }) updatedAt!: Date;
  @Property({ version: true }) version = 1;
}
