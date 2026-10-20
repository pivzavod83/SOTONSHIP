import test from 'node:test';
import assert from 'node:assert/strict';
import { projectParserExperiment } from '../benchmark-ui/parser-catalog.mjs';

// Adapter contracts deliberately distinguish missing measurements, measured zeros,
// and unresolved outcomes. These fixtures are not benchmark performance results.
const metric = (count, denominator, unknown = 0) => ({ count, denominator, unknown,
  failed: denominator - count - unknown, status: 'MEASURED' });
const triple = denominator => ({ syntaxParsed: metric(denominator, denominator),
  namesTypesResolved: metric(0, denominator, denominator), semanticsModeled: metric(0, denominator, denominator) });
const fixture = () => ({
  schemaVersion: 1, kind: 'PARSER_FRONTEND_COVERAGE', experimentId: 'parser-v3',
  sourcesExecuted: false, modelTrained: false, modelInferencePerformed: false, accuracy: null, recall: null,
  profiles: Object.fromEntries(['FREE', 'FIXED'].map(profile => [profile, { pairs: 10, metrics: triple(10) }])),
  baseline: { id: 'typed-v2', profiles: Object.fromEntries(['FREE', 'FIXED'].map(profile => [profile, { pairs: 10, metrics: {
    syntaxParsed: { count: null, denominator: 10, status: 'NOT_SEPARATELY_MEASURED' },
    namesTypesResolved: { count: null, denominator: 10, status: 'NOT_SEPARATELY_MEASURED' },
    semanticsModeled: { count: 0, denominator: 10, status: 'MEASURED' },
  } }])) },
  sourcesByLanguage: { Java: { sources: 10, metrics: triple(10) },
    COBOL: { profiles: Object.fromEntries(['FREE', 'FIXED'].map(profile => [profile, { sources: 15, metrics: triple(15) }])) } },
  failureExamples: [{ language: 'COBOL', profile: 'FREE', path: 'data/p00001/COBOL/example.cob', stage: 'resolution',
    line: 8, message: 'Type analysis is unavailable under this analysis contract.' }],
});

test('parser experiment keeps syntax, resolution and semantic coverage separate from trained models', () => {
  const result = projectParserExperiment({ report: fixture(), source: { reportPath: 'report.json' } });
  assert.equal(result.kind, 'PARSER_EXPERIMENTS');
  assert.equal(result.versions.length, 2);
  assert.equal(result.versions[0].profiles.FREE.metrics.syntaxParsed.count, null);
  assert.equal(result.versions[0].profiles.FREE.metrics.namesTypesResolved.count, null);
  assert.equal(result.versions[0].profiles.FREE.metrics.semanticsModeled.count, 0);
  const v3 = result.versions[1];
  assert.equal(v3.id, 'parser-v3');
  assert.deepEqual(v3.profiles.FREE.metrics.namesTypesResolved, metric(0, 10, 10));
  assert.equal(v3.profiles.FREE.metrics.syntaxParsed.count, 10);
  assert.equal(v3.languageResults.find(item => item.language === 'Java').metrics.syntaxParsed.denominator, 10);
  assert.equal(v3.languageResults.find(item => item.language === 'COBOL').metrics.syntaxParsed.denominator, 15);
  assert.equal(v3.accuracy, undefined);
  assert.match(v3.summary, /unchanged shared semantic IR/);
  assert.equal(v3.failureExamples[0].line, 8);
});

test('parser report rejects fabricated accuracy, executed sources and incomplete outcome accounting', () => {
  for (const change of [
    report => { report.accuracy = 1; },
    report => { report.sourcesExecuted = true; },
    report => { report.modelTrained = true; },
    report => { report.profiles.FREE.metrics.syntaxParsed.unknown = 1; },
    report => { report.profiles.FREE.metrics.semanticsModeled = metric(1, 10); },
    report => { report.baseline.profiles.FREE.metrics.syntaxParsed.count = 0; },
    report => { report.sourcesByLanguage.Java.sources = 20; },
    report => { report.profiles.FIXED.pairs = 11; },
  ]) {
    const report = fixture(); change(report);
    assert.throws(() => projectParserExperiment({ report }), /Parser V3 coverage contract/);
  }
});

test('separate compiler failures retain their explicit source-format probes', () => {
  const report = fixture();
  report.profiles.FIXED.metrics = { syntaxParsed: metric(6, 10, 1),
    namesTypesResolved: metric(0, 10, 7), semanticsModeled: metric(0, 10, 7) };
  const projected = projectParserExperiment({ report }).versions[1];
  assert.equal(projected.profiles.FREE.metrics.syntaxParsed.count, 10);
  assert.equal(projected.profiles.FIXED.metrics.syntaxParsed.count, 6);
  assert.equal(projected.profiles.FIXED.metrics.syntaxParsed.failed, 3);
  assert.equal(projected.profiles.FIXED.metrics.syntaxParsed.unknown, 1);
});
