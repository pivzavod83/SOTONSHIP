import { Entity, PrimaryKey, Property, Unique } from '@mikro-orm/core';
import { JsonObject } from '../../../common/value-objects/json-value';

@Entity({ tableName: 'reference_fx_rates' })
@Unique({ properties: ['currencyPair', 'source', 'collectedDate'] })
export class ReferenceFxRateEntity {
  @PrimaryKey({ type: 'uuid' }) id!: string;
  @Property({ length: 7 }) currencyPair!: string;
  @Property({ type: 'decimal', precision: 24, scale: 12 }) rate!: string;
  @Property({ length: 300 }) source!: string;
  @Property({ length: 10 }) collectedDate!: string;
  @Property({ length: 10, nullable: true }) observationDate?: string;
  @Property({ type: 'json', defaultRaw: "'{}'::jsonb" }) provenanceJson: JsonObject = {};
}
