import { Migration } from '@mikro-orm/migrations';

/** Preserve market/survey vintage separately from the day a source was collected. */
export class Migration20261017000200 extends Migration {
  async up(): Promise<void> {
    this.addSql('alter table "reference_fx_rates" add column "observation_date" varchar(10) null;');
    this.addSql(`alter table "reference_fx_rates" add column "provenance_json" jsonb not null default '{}'::jsonb;`);
  }
  async down(): Promise<void> {
    this.addSql('alter table "reference_fx_rates" drop column "observation_date", drop column "provenance_json";');
  }
}
