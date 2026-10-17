import { Migration } from '@mikro-orm/migrations';

export class Migration20261017000100 extends Migration {
  async up(): Promise<void> {
    this.addSql(`create table "reference_fx_rates" (
      "id" uuid not null, "currency_pair" varchar(7) not null,
      "rate" numeric(24,12) not null check ("rate" > 0), "source" varchar(300) not null,
      "collected_date" varchar(10) not null,
      constraint "reference_fx_rates_pkey" primary key ("id"),
      constraint "reference_fx_rates_currency_pair_source_collected_date_unique" unique ("currency_pair", "source", "collected_date")
    );`);
    this.addSql(`create table "verifications" (
      "id" uuid not null, "module_name" varchar(160) not null,
      "category" varchar(255) not null check ("category" in ('FX_CONVERSION','INTEREST_CALC','REMITTANCE_FEE','EXTERNAL_LIMIT_CASE')),
      "cobol_source" text not null, "java_source" text not null, "patched_java_source" text not null,
      "gnn_alignment_score" double precision not null check ("gnn_alignment_score" between 0 and 1),
      "gnn_bug_risk_score" double precision not null check ("gnn_bug_risk_score" between 0 and 1),
      "baseline_alignment_score" double precision not null check ("baseline_alignment_score" between 0 and 1),
      "baseline_caught_bug" boolean not null,
      "formal_proof_status" varchar(255) not null check ("formal_proof_status" in ('SAT_COUNTEREXAMPLE_FOUND','UNSAT_PROVEN_SAFE','UNKNOWN_HALTED_LIMIT')),
      "bug_category" varchar(255) not null, "f_string_summary" text not null,
      "cpg_graph_json" jsonb not null, "counterexamples_json" jsonb not null,
      "is_failure_limit_case" boolean not null, "proof_scope" jsonb not null, "provenance_json" jsonb not null,
      "created_at" timestamptz not null, "updated_at" timestamptz not null,
      "version" integer not null default 1,
      constraint "verifications_pkey" primary key ("id"),
      constraint "verification_limit_not_safe" check (not "is_failure_limit_case" or "formal_proof_status" = 'UNKNOWN_HALTED_LIMIT')
    );`);
    this.addSql('create index "verifications_created_at_index" on "verifications" ("created_at");');
  }
  async down(): Promise<void> {
    this.addSql('drop table if exists "verifications";');
    this.addSql('drop table if exists "reference_fx_rates";');
  }
}
