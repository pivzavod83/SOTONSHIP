import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { readFile, mkdtemp, mkdir, writeFile, rm, cp } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { buildCatalog, REPORT_FILES } from '../benchmark-ui/catalog.mjs';

const repoRoot = fileURLToPath(new URL('../..', import.meta.url));
const catalogPromise = buildCatalog({ repoRoot, generatedAt: '2026-10-20T00:00:00.000Z' });
const json = async relative => JSON.parse(await readFile(path.join(repoRoot, relative), 'utf8'));
const version = (catalog, id) => catalog.versions.find(item => item.id === id);

test('catalog separates all recorded defect and matching versions without inventing R1 model', async () => {
  const catalog = await catalogPromise;
  assert.equal(catalog.versions.length, 11);
  assert.equal(catalog.versions.filter(item => item.task === 'defect').length, 3);
  assert.equal(catalog.versions.filter(item => item.task === 'matching').length, 8);
  assert.equal(catalog.versions.filter(item => item.id.startsWith('matching-v4-')).length, 5);
  assert.equal(catalog.versions.some(item => item.id.includes('pilot-r1')), false);
  assert.equal(catalog.methodology.trainingPerformed, false);
  assert.equal(catalog.methodology.inferencePerformed, false);
  assert.equal(catalog.repository.branch, 'research/benchmark-dashboard');
  assert.match(catalog.repository.branchUrl, /\/tree\/research\/benchmark-dashboard$/);
  assert.equal(catalog.generatedAt, '2026-10-20T00:00:00.000Z');
});

test('defect metrics bind to recorded reports and preserve unknown versus zero', async () => {
  const catalog = await catalogPromise;
  const original = version(catalog, 'defect-v1').assessments[0];
  assert.equal(original.metrics.accuracy, 0.125);
  assert.equal(original.metrics.recall, 0.25);
  assert.deepEqual([original.counts.tp, original.counts.tn, original.counts.fp, original.counts.fn], [1, 0, 4, 3]);
  assert.equal(original.metrics.top1, null);
  assert.equal(original.source.integrity, 'verified');
  for (const arm of ['v1-refit-control', 'typed-v2']) {
    const current = version(catalog, `defect-${arm}`);
    const regression = current.assessments[0];
    assert.equal(regression.metrics.accuracy, 0.5);
    assert.equal(regression.metrics.recall, 0.75);
    assert.equal(regression.metrics.missedDefects, 1);
    assert.equal(regression.metrics.reviewWorkload, 0.75);
    assert.equal(regression.counts.autonomousAcceptances, 0);
    assert.equal(regression.reused, true);
    assert.equal(regression.source.integrity, 'unverified');
    assert.ok(regression.source.checks.every(check => check.verified));
    assert.match(regression.source.integrityScope, /no independent recorded report hash/);
    assert.equal(current.assessments.find(item => item.id === 'oof').pairs, 24);
  }
  assert.equal(version(catalog, 'defect-typed-v2').assessments.find(item => item.id === 'validation').metrics.accuracy, 0.625);
  assert.equal(version(catalog, 'defect-v1-refit-control').assessments[0].coverage.strictCoverageProvided, false);
  assert.equal(version(catalog, 'defect-v1-refit-control').assessments[0].coverage.supportedPairs, null);
});

test('matching metrics keep the 29 and 23 candidate galleries distinct', async () => {
  const catalog = await catalogPromise;
  const v1 = version(catalog, 'matching-v1');
  assert.equal(v1.assessments[0].counts.candidatesPerQuery, 29);
  const shared = v1.assessments.find(item => item.id === 'shared-23');
  assert.equal(shared.metrics.top1, 11 / 23);
  assert.equal(shared.counts.candidatesPerQuery, 23);
  assert.notEqual(shared.cohort, v1.assessments[0].cohort);
  const final = await json('ml-engine/evaluation/paired-code/cv-v4-candidates/final-evaluation-report.json');
  for (const candidate of ['baseline', 'structural_cca', 'graph_regularized', 'language_heads', 'count_readout']) {
    const entry = version(catalog, `matching-v4-${candidate}`);
    assert.equal(entry.assessments[0].metrics.top1, final.metrics[candidate].top1);
    assert.equal(entry.assessments[0].metrics.mrr, final.metrics[candidate].mrr);
    assert.equal(entry.assessments[0].metrics.accuracy, null);
    assert.equal(entry.assessments[0].metrics.missedDefects, null);
    assert.equal(entry.assessments[0].source.integrity, 'verified');
    assert.equal(entry.assessments[1].counts.candidatesPerQuery, 24);
  }
  assert.equal(version(catalog, 'matching-v4-graph_regularized').status, 'deployed');
  assert.equal(version(catalog, 'matching-v4-language_heads').selectedByDevelopmentCv, false);
});

test('every report download uses a fixed allowlisted artifact and each metric has a source', async () => {
  const catalog = await catalogPromise;
  assert.equal(Object.isFrozen(REPORT_FILES), true);
  for (const entry of catalog.versions) {
    assert.equal(entry.source.reportPath, REPORT_FILES[entry.id]);
    for (const assessment of entry.assessments) {
      assert.ok(assessment.source.reportPath.startsWith('ml-engine/evaluation/'));
      assert.match(assessment.source.sha256, /^[0-9a-f]{64}$/);
      assert.match(assessment.source.reportUrl, /\/blob\/[0-9a-f]{40}\//);
      assert.equal(assessment.reused, true);
      for (const [name, value] of Object.entries(assessment.metrics)) {
        assert.ok(value === null || Number.isFinite(value));
        if (value !== null && name !== 'missedDefects') assert.ok(value >= 0 && value <= 1);
      }
    }
  }
});

test('case study uses the exact audited source and observed runtime mismatch, not model success', async () => {
  const { caseStudy } = await catalogPromise;
  const dataset = await json('ml-engine/evaluation/synthetic-pilot/pilot-10-r3/dataset.json');
  const family = dataset.families.find(item => item.familyId === 'F005');
  assert.equal(caseStudy.cobolCode, family.cobolLines.join('\n'));
  assert.equal(caseStudy.javaCode, family.variants.find(item => item.variantId === 'F005-V4').javaLines.join('\n'));
  assert.equal(caseStudy.javaCode.split('\n')[caseStudy.culprit.startLine - 1].trim(), 'long cashStepCents = 10L;');
  assert.equal(caseStudy.witness.stdin, '12.34\n1.2500\n');
  assert.equal(caseStudy.witness.cobolOutput, '15.45');
  assert.equal(caseStudy.witness.javaOutput, '15.40');
  assert.equal(caseStudy.witness.mismatch, true);
  assert.equal(caseStudy.witness.executedNow, false);
  assert.equal(caseStudy.evidence.integrity, 'verified');
  assert.ok(caseStudy.evidence.checks.every(check => check.verified));
  assert.equal(caseStudy.modelFindings.length, 3);
  assert.equal(caseStudy.modelFindings[0].predictedDefect, false);
  assert.equal(caseStudy.modelFindings[2].decision, 'NO_DEFECT_SIGNAL');
});

test('contracts are extraction checks, not fabricated accuracy examples', async () => {
  const { contracts } = await catalogPromise;
  assert.deepEqual([contracts.fixtureCount, contracts.passed, contracts.failed], [8, 8, 0]);
  assert.equal(contracts.codeExecuted, false);
  assert.equal(contracts.modelTrained, false);
  assert.equal(contracts.source.integrity, 'verified');
});

test('a corrupted hash-bound model cannot retain verified integrity', async () => {
  // Copy only the small JSON/source artifacts read by the catalog. No model execution.
  const scratch = await mkdtemp(path.join(os.tmpdir(), 'benchmark-catalog-'));
  try {
    const original = await catalogPromise;
    const files = new Set([DATASET_PATH, ...Object.values(REPORT_FILES)]);
    const extra = [
      'ml-engine/evaluation/synthetic-pilot/defect-model-v1/validation-evaluation.json',
      'ml-engine/evaluation/synthetic-pilot/defect-model-v1/candidate-selection.json',
      'ml-engine/evaluation/synthetic-pilot/defect-model-v1/frozen-artifact.json',
      'ml-engine/evaluation/synthetic-pilot/defect-model-v1/artifact-hashes.json',
      'ml-engine/evaluation/extractor-v2/pilot-r2/frozen-artifact.json',
      'ml-engine/evaluation/extractor-v2/pilot-r2/protocol.json',
      'ml-engine/evaluation/extractor-v2/pilot-r2/contract-diagnostics.json',
      'ml-engine/evaluation/extractor-v2/pilot-r2/grouped-oof-evaluation.json',
      'ml-engine/evaluation/extractor-v2/pilot-r2/validation-evaluation.json',
      'ml-engine/evaluation/synthetic-pilot/batch-03-f005-r2/runtime-audit-2026-10-18/artifact-hashes.json',
      'ml-engine/evaluation/synthetic-pilot/batch-03-f005-r2/runtime-audit-2026-10-18/source-hashes.json',
    ];
    extra.forEach(file => files.add(file));
    for (const directory of ['cv-v2', 'cv-v3-fold-ensemble', 'cv-v4-candidates']) {
      for (const file of ['deployment-manifest.json', 'model-freeze.json', 'cv-training-report.json']) files.add(`ml-engine/evaluation/paired-code/${directory}/${file}`);
    }
    files.add('ml-engine/evaluation/paired-code/cv-v4-candidates/run-plan.json');
    for (const entry of original.versions) for (const assessment of entry.assessments) {
      files.add(assessment.source.reportPath);
      assessment.source.checks.forEach(check => files.add(check.path));
    }
    files.add(original.caseStudy.evidence.reportPath);
    for (const file of files) {
      await mkdir(path.dirname(path.join(scratch, file)), { recursive: true });
      await cp(path.join(repoRoot, file), path.join(scratch, file));
    }
    await writeFile(path.join(scratch, 'ml-engine/ml_engine/models/defect_model_v1.json'), '{}');
    const corrupted = await buildCatalog({ repoRoot: scratch });
    const source = version(corrupted, 'defect-v1').source;
    assert.equal(source.integrity, 'unverified');
    assert.equal(source.checks.find(check => check.path.endsWith('defect_model_v1.json')).verified, false);
    assert.equal(corrupted.repository.commit, null);
    assert.equal(source.commitUrl, null);
  } finally { await rm(scratch, { recursive: true, force: true }); }
});

const DATASET_PATH = 'ml-engine/evaluation/synthetic-pilot/pilot-10-r3/dataset.json';
