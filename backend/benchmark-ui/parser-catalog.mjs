/** An explicit projection of parser coverage, separate from trained ML versions. */
export const PARSER_DIRECTORY = 'ml-engine/evaluation/parser-v3/codenet-r1';
export const PARSER_REPORT = `${PARSER_DIRECTORY}/report.json`;
const stages = ['syntaxParsed', 'namesTypesResolved', 'semanticsModeled'];
const profiles = ['FREE', 'FIXED'];
const fail = message => { throw new Error(`Parser V3 coverage contract: ${message}`); };

function projectMetrics(value, denominator, { historical = false } = {}) {
  if (!Number.isInteger(denominator) || denominator < 0) fail('invalid denominator');
  const result = {};
  for (const key of stages) {
    const record = value?.[key];
    if (!record || record.denominator !== denominator) fail(`${key} denominator mismatch`);
    if (historical && key !== 'semanticsModeled') {
      if (record.count !== null || !['NOT_SEPARATELY_MEASURED', 'NOT_MEASURED'].includes(record.status)) fail(`${key} baseline must remain unmeasured`);
      result[key] = { count: null, denominator, status: record.status, unknown: null, failed: null };
      continue;
    }
    if (record.status !== 'MEASURED' || !Number.isInteger(record.count) || record.count < 0 || record.count > denominator) fail(`${key} invalid count or status`);
    if (!historical) {
      if (![record.unknown, record.failed].every(count => Number.isInteger(count) && count >= 0)
          || record.count + record.unknown + record.failed !== denominator) fail(`${key} outcomes do not partition the denominator`);
    }
    result[key] = { count: record.count, denominator, status: record.status,
      unknown: record.unknown ?? null, failed: record.failed ?? null };
  }
  if (!historical && (result.namesTypesResolved.count > result.syntaxParsed.count
      || result.semanticsModeled.count > result.namesTypesResolved.count)) fail('completed stages must be nested');
  return result;
}

export function projectParserExperiment({ report, source, baselineSource, protocolUrl, documentationUrl }) {
  if (report.schemaVersion !== 1 || report.kind !== 'PARSER_FRONTEND_COVERAGE' || report.experimentId !== 'parser-v3'
      || report.sourcesExecuted !== false || report.modelTrained !== false || report.modelInferencePerformed !== false
      || report.accuracy !== null || report.recall !== null) fail('unexpected experiment or execution/ML claim');
  if (report.baseline?.id !== 'typed-v2') fail('expected frozen typed V2 baseline');
  const projectedProfiles = (input, historical = false) => Object.fromEntries(profiles.map(profile => {
    const record = input?.[profile];
    if (!record || !Number.isInteger(record.pairs) || record.pairs < 1) fail(`${profile} missing pair count`);
    return [profile, { pairs: record.pairs, metrics: projectMetrics(record.metrics, record.pairs, { historical }) }];
  }));
  const current = projectedProfiles(report.profiles), baseline = projectedProfiles(report.baseline.profiles, true);
  for (const profile of profiles) if (current[profile].pairs !== baseline[profile].pairs) fail('current/baseline cohort mismatch');
  const java = report.sourcesByLanguage?.Java, cobol = report.sourcesByLanguage?.COBOL;
  if (!java || !cobol?.profiles) fail('missing language results');
  const languageResults = [{ language: 'Java', metrics: projectMetrics(java.metrics, java.sources),
    note: 'Unique selected Java sources; semantic analysis uses the recorded compiler configuration.' },
  ...profiles.map(profile => {
    const record = cobol.profiles[profile];
    if (!record) fail(`missing COBOL ${profile} result`);
    return { language: 'COBOL', profile, metrics: projectMetrics(record.metrics, record.sources),
      note: 'All retained COBOL sources; each explicit source-format probe is reported separately.' };
  })];
  const examples = report.failureExamples ?? [];
  if (!Array.isArray(examples) || examples.some(item => !['Java', 'COBOL'].includes(item.language)
      || item.profile && !profiles.includes(item.profile))) fail('invalid failure examples');
  return {
    kind: 'PARSER_EXPERIMENTS', status: 'RECORDED', protocolUrl, documentationUrl,
    metricsAre: 'Source coverage counts, not classifier accuracy or equivalence results.',
    versions: [
      { id: 'parser-typed-v2', name: 'Parser V2 · bounded handwritten frontends', status: 'FROZEN BASELINE',
        scope: 'Same selected source pairs. Syntax and resolution were not separately measured in the historical audit.',
        profiles: baseline, source: baselineSource },
      { id: 'parser-v3', name: 'Parser V3 · compiler frontends', status: 'EXPERIMENTAL',
        summary: 'Compiler-backed syntax coverage is measured separately from name/type resolution and the unchanged shared semantic IR lowerer.',
        scope: 'Same selected source pairs. FREE/FIXED are explicit probes; no automatic dialect or source-format assumption.',
        profiles: current, languageResults, failureExamples: examples,
        changes: report.changes ?? ['Uses established Java and COBOL frontends for syntax.',
          'Records syntax, complete name/type resolution, and shared semantic representation separately.',
          'Retains the existing typed IR lowerer; a parsed AST does not count as modeled behavior.'],
        limitations: report.limitations ?? report.warnings ?? ['CodeNet programs are not validated translation pairs.',
          'Syntax recognition does not establish semantic equivalence.', 'No new defect model is trained or deployed by this experiment.'],
        source },
    ],
  };
}
