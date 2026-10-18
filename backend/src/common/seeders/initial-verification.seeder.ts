import { EntityManager } from '@mikro-orm/core';
import { Seeder } from '@mikro-orm/seeder';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { VerificationEntity } from '../../modules/verification/entities/verification.entity';
import { VerificationRun, VerificationRunProps } from '../../modules/verification/domain/entities/verification-run';
import { VerificationMapper } from '../../modules/verification/infrastructure/mappers/verification.mapper';
import { ReferenceFxRateEntity } from '../../modules/fx-rates/entities/reference-fx-rate.entity';
import { ReferenceFxRate, ReferenceFxRateProps } from '../../modules/fx-rates/domain/entities/reference-fx-rate';
import { ReferenceFxRateMapper } from '../../modules/fx-rates/infrastructure/mappers/reference-fx-rate.mapper';
import { JsonObject } from '../value-objects/json-value';

interface Fixture {
  referenceFxRates: ReferenceFxRateProps[];
  verifications: (Omit<VerificationRunProps, 'createdAt' | 'updatedAt'> & { createdAt?: string; updatedAt?: string })[];
}

/** Inserts only missing stable IDs; rerunning seeds preserves applied patches. */
export class InitialVerificationSeeder extends Seeder {
  async run(em: EntityManager): Promise<void> {
    const path = resolve(process.env.SEED_DATA_PATH ?? '../ml-engine/data/seed-verifications.json');
    const fixture: Fixture = JSON.parse(await readFile(path, 'utf8')) as Fixture;
    if (!Array.isArray(fixture.referenceFxRates) || !Array.isArray(fixture.verifications) || fixture.verifications.length !== 4) {
      throw new Error('Expected a precomputed fixture with referenceFxRates and exactly four verifications. Run the Python precomputation script.');
    }
    await em.transactional(async (transaction) => {
      for (const input of fixture.referenceFxRates) {
        const existing = await transaction.findOne(ReferenceFxRateEntity, {
          currencyPair: input.currencyPair, source: input.source, collectedDate: input.collectedDate,
        });
        if (existing) continue;
        const { id, currencyPair, rate: exactRate, source, collectedDate, observationDate, provenanceJson, ...metadata } = input;
        const rate = new ReferenceFxRate({
          id: id ?? randomUUID(), currencyPair, rate: String(exactRate), source, collectedDate, observationDate,
          provenanceJson: { ...metadata, ...provenanceJson } as JsonObject,
        });
        transaction.persist(ReferenceFxRateMapper.toPersistence(rate));
      }
      for (const input of fixture.verifications) {
        if (await transaction.findOne(VerificationEntity, { id: input.id })) continue;
        const run = new VerificationRun({
          ...input, createdAt: new Date(input.createdAt ?? Date.now()), updatedAt: new Date(input.updatedAt ?? Date.now()),
          version: input.version ?? 1,
        });
        transaction.persist(VerificationMapper.toPersistence(run));
      }
      await transaction.flush();
    });
  }
}
