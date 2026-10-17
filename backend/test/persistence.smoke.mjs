/** Real PostgreSQL concurrency check. Build and migrate a disposable database first. */
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { MikroORM } from '@mikro-orm/postgresql';
import ormConfiguration from '../dist/mikro-orm.config.js';
import repositoryModule from '../dist/modules/verification/infrastructure/repositories/mikro-orm-verification.repository.js';
import entityModule from '../dist/modules/verification/entities/verification.entity.js';
import domainModule from '../dist/modules/verification/domain/entities/verification-run.js';
import idModule from '../dist/modules/verification/domain/value-objects/verification-id.js';
const { MikroOrmVerificationRepository } = repositoryModule;
const { VerificationEntity } = entityModule;
const { VerificationRun } = domainModule;
const { VerificationId } = idModule;
const orm = await MikroORM.init(ormConfiguration.default);
try {
  const fork = () => { const em = orm.em.fork(); return new MikroOrmVerificationRepository(em.getRepository(VerificationEntity), em); };
  const rows = fork();
  const template = (await rows.findAll())[0].toPrimitives();
  const id = randomUUID();
  await rows.save(new VerificationRun({ ...template, id, moduleName: 'PERSISTENCE-CONFLICT.cbl', version: 1, createdAt: new Date(), updatedAt: new Date() }));
  const first = fork(), second = fork();
  const [a, b] = await Promise.all([first.findById(new VerificationId(id)), second.findById(new VerificationId(id))]);
  const outcomes = await Promise.allSettled([first.save(new VerificationRun({ ...a.toPrimitives(), updatedAt: new Date() })),
    second.save(new VerificationRun({ ...b.toPrimitives(), updatedAt: new Date() }))]);
  assert.equal(outcomes.filter(outcome => outcome.status === 'fulfilled').length, 1, 'Exactly one stale-version writer may commit');
  assert.equal(outcomes.find(outcome => outcome.status === 'rejected').reason.code, 'verification.conflict');
  const history = await orm.em.getConnection().execute('select version from verification_revisions where verification_id = ? order by version', [id]);
  assert.deepEqual(history.map(row => row.version), [1, 2], 'The losing transaction must not leave a partial or duplicate revision');
  console.log('Persistence integration passed: conflicting writes return 409 and revision history is atomic.');
} finally { await orm.close(true); }
