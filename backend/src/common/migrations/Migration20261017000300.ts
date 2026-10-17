import { Migration } from '@mikro-orm/migrations';
export class Migration20261017000300 extends Migration {
  async up(): Promise<void> {
    this.addSql('create table "verification_revisions" ("id" uuid not null, "verification_id" uuid not null, "version" int not null, "recorded_at" timestamptz not null, "snapshot_json" jsonb not null, constraint "verification_revisions_pkey" primary key ("id"), constraint "verification_revisions_version_unique" unique ("verification_id", "version"));');
    this.addSql('alter table "verification_revisions" add constraint "verification_revisions_run_fk" foreign key ("verification_id") references "verifications" ("id");');
  }
  async down(): Promise<void> { this.addSql('drop table "verification_revisions";'); }
}
