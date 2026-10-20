/** Read-only projection of recorded experiments. No training or model inference. */
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import path from 'node:path';

const run = promisify(execFile);
const DEFECT = 'ml-engine/evaluation/synthetic-pilot/defect-model-v1';
const EXTRACTOR = 'ml-engine/evaluation/extractor-v2/pilot-r2';
const MATCHING = 'ml-engine/evaluation/paired-code';
const DATASET = 'ml-engine/evaluation/synthetic-pilot/pilot-10-r3/dataset.json';
const AUDIT = 'ml-engine/evaluation/synthetic-pilot/batch-03-f005-r2/runtime-audit-2026-10-18';
const metricKeys = ['accuracy', 'precision', 'recall', 'f1', 'top1', 'top3', 'top5', 'mrr', 'hitAt1', 'hitAt3', 'reviewWorkload', 'missedDefects'];
const digest = value => createHash('sha256').update(value).digest('hex');
const number = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
const metrics = value => Object.fromEntries(metricKeys.map(key => [key, number(value?.[key])]));
const encodePath = value => value.split('/').map(encodeURIComponent).join('/');

/** Fixed report allowlist; request parameters never become filesystem paths. */
export const REPORT_FILES = Object.freeze({
  'defect-v1': `${DEFECT}/final-test-evaluation.json`,
  'defect-v1-refit-control': `${EXTRACTOR}/regression-test-evaluation.json`,
  'defect-typed-v2': `${EXTRACTOR}/regression-test-evaluation.json`,
  'matching-v1': `${MATCHING}/cv-v2/final-evaluation-report.json`,
  'matching-v2': `${MATCHING}/cv-v2/final-evaluation-report.json`,
  'matching-v3': `${MATCHING}/cv-v3-fold-ensemble/final-evaluation-report.json`,
  ...Object.fromEntries(['baseline', 'structural_cca', 'graph_regularized', 'language_heads', 'count_readout']
    .map(id => [`matching-v4-${id}`, `${MATCHING}/cv-v4-candidates/final-evaluation-report.json`])),
});

export async function buildCatalog({
  repoRoot,
  repositoryUrl = 'https://github.com/pivzavod83/SOTONSHIP',
  branch = 'research/benchmark-dashboard',
  generatedAt = new Date().toISOString(),
} = {}) {
  if (!repoRoot) throw new TypeError('repoRoot is required');
  const root = path.resolve(repoRoot);
  const url = repositoryUrl.replace(/\/$/, '');
  const branchUrl = `${url}/tree/${encodePath(branch)}`;
  const cache = new Map();
  const loadBytes = file => {
    if (!cache.has(file)) cache.set(file, readFile(path.join(root, file)));
    return cache.get(file);
  };
  const load = async file => JSON.parse(await loadBytes(file));
  const git = async args => {
    try { return (await run('git', ['-C', root, ...args], { maxBuffer: 1024 * 1024 })).stdout.trim() || null; }
    catch { return null; }
  };
  const commit = await git(['rev-parse', 'HEAD']);
  const commitUrl = commit ? `${url}/commit/${commit}` : null;
  const checks = async entries => Promise.all(entries.map(async ([file, expected]) => {
    let actual = null;
    try { actual = digest(await loadBytes(file)); } catch { /* A missing artifact must fail its check. */ }
    return { path: file, expectedSha256: expected ?? null, actualSha256: actual,
      verified: typeof expected === 'string' && actual === expected };
  }));
  const source = async (file, expected = null, bindings = []) => {
    const reportCommit = await git(['log', '-1', '--format=%H', '--', file]);
    const contentChecks = await checks(expected ? [[file, expected], ...bindings] : bindings);
    const hasReportBinding = contentChecks.some(check => check.path === file && check.verified);
    return {
      branchUrl, commit: reportCommit, commitUrl: reportCommit ? `${url}/commit/${reportCommit}` : null,
      reportPath: file,
      reportUrl: `${url}/blob/${reportCommit ?? encodePath(branch)}/${encodePath(file)}`,
      sha256: digest(await loadBytes(file)),
      integrity: hasReportBinding && contentChecks.every(check => check.verified) ? 'verified' : 'unverified',
      integrityScope: hasReportBinding ? 'Compared with recorded SHA-256 bindings; not a semantic or statistical validity claim.'
        : 'SHA-256 computed for this report; no independent recorded report hash is available. Related bindings are checked separately.',
      checks: contentChecks,
    };
  };
  const assessment = async ({ id, label, scope, reused, data, file, expected, bindings, notes = [], cohort }) => {
    const confusion = data.confusion ?? {};
    const local = data.localization ?? data.localizationWeakLabels ?? {};
    const tp = number(confusion.truePositive), fp = number(confusion.falsePositive), fn = number(confusion.falseNegative);
    const pairCount = number(data.pairs ?? data.queries);
    const review = number(data.reviewWorkloadFraction) ?? (pairCount && tp !== null && fp !== null ? (tp + fp) / pairCount : null);
    return {
      id, label, scope, reused, cohort, pairs: pairCount,
      metrics: metrics({ ...data, hitAt1: local.hitAt1, hitAt3: local.hitAt3, reviewWorkload: review,
        missedDefects: number(data.nonFlaggedDefects) ?? fn }),
      counts: { tp, tn: number(confusion.trueNegative), fp, fn, correct: number(data.correct),
        reviewedPairs: number(data.reviewedPairs), nonFlaggedPairs: number(data.nonFlaggedPairs),
        defectivePairs: number(local.defectivePairs), queries: number(data.queries),
        candidatesPerQuery: number(data.candidatesPerQuery), autonomousAcceptances: number(data.autonomousAcceptances) },
      notes, source: await source(file, expected, bindings),
    };
  };

  const [v1Final, v1Validation, v1Selection, v1Freeze, v1HashManifest, v2Final, v2Oof, v2Validation, v2Freeze, v2Protocol,
    v2Contracts, v1Matching, matchingV2, matchingV3, matchingV4, v4Training, v4Plan] = await Promise.all([
    load(`${DEFECT}/final-test-evaluation.json`), load(`${DEFECT}/validation-evaluation.json`),
    load(`${DEFECT}/candidate-selection.json`), load(`${DEFECT}/frozen-artifact.json`), load(`${DEFECT}/artifact-hashes.json`),
    load(`${EXTRACTOR}/regression-test-evaluation.json`), load(`${EXTRACTOR}/grouped-oof-evaluation.json`),
    load(`${EXTRACTOR}/validation-evaluation.json`), load(`${EXTRACTOR}/frozen-artifact.json`), load(`${EXTRACTOR}/protocol.json`),
    load(`${EXTRACTOR}/contract-diagnostics.json`), load(`${MATCHING}/training-report.json`),
    load(`${MATCHING}/cv-v2/final-evaluation-report.json`), load(`${MATCHING}/cv-v3-fold-ensemble/final-evaluation-report.json`),
    load(`${MATCHING}/cv-v4-candidates/final-evaluation-report.json`), load(`${MATCHING}/cv-v4-candidates/cv-training-report.json`),
    load(`${MATCHING}/cv-v4-candidates/run-plan.json`),
  ]);
  const versions = [];
  const v1Bindings = [
    ['ml-engine/ml_engine/models/defect_model_v1.json', v1Freeze.sha256], [DATASET, v1Freeze.datasetSha256],
    ...Object.entries(v1Freeze.implementationHashes).map(([file, hash]) => [`ml-engine/${file}`, hash]),
  ];
  const originalAssessment = async (id, label, file, data, scope, cohort) => assessment({ id, label, file, data, scope, cohort,
    reused: true, expected: v1HashManifest.files[file], bindings: v1Bindings,
    notes: ['Synthetic AI-generated pairs; intended-equivalent means matches executed inputs, not a proof.',
      'Localization uses weak AI-generated spans.', 'Low risk scores never authorize acceptance.'] });
  const selected = v1Selection.candidates.find(candidate => candidate.C === v1Selection.selectedC && candidate.architecture === v1Selection.selectedArchitecture);
  const originalAssessments = [
    await originalAssessment('regression', 'Original test / now reused', `${DEFECT}/final-test-evaluation.json`, v1Final,
      'Eight previously inspected pairs from two source families; descriptive pilot results.', 'synthetic-F005-F010-8'),
    await originalAssessment('validation', 'Validation', `${DEFECT}/validation-evaluation.json`, v1Validation,
      'Eight pairs from F004/F009. Validation diagnostics, not external performance.', 'synthetic-F004-F009-8'),
    ...(selected ? [await originalAssessment('oof', 'Grouped CV selection', `${DEFECT}/candidate-selection.json`, selected.metrics,
      '24 development pairs / six families; used for model selection, not unbiased nested CV.', 'synthetic-development-24')] : []),
  ];
  versions.push({
    id: 'defect-v1', name: 'Defect V1 · heuristic features', task: 'defect', status: 'deployed',
    summary: 'Three-fold ensemble of logistic span rankers and pair classifiers; source-only heuristic graphs.',
    changes: ['First trained local defect detector.', 'Family-grouped folds; 24 training, 8 validation and 8 test pairs.'],
    problems: ['Missed three of four labelled test defects.', 'Heuristic extraction silently loses some operations and type behavior.',
      'Only ten synthetic source families; localization labels have not been expert reviewed.'],
    nextSteps: ['Improve numeric semantic comparisons and collect independent defect families.', 'Keep a fresh family-level external evaluation set.'],
    threshold: v1Freeze.threshold, defaultAssessmentId: 'regression', source: originalAssessments[0].source,
    assessments: originalAssessments,
  });
  const v2Bindings = [
    [`${EXTRACTOR}/model.json`, v2Freeze.modelSha256], [DATASET, v2Freeze.datasetSha256],
    ['ml-engine/evaluation/synthetic-pilot/pilot-10-r3/split-plan.json', v2Freeze.splitPlanSha256],
    [`${EXTRACTOR}/protocol.json`, v2Freeze.protocolSha256], [`${EXTRACTOR}/contract-diagnostics.json`, v2Freeze.contractAuditSha256],
    ...Object.entries(v2Freeze.implementationHashes).map(([file, hash]) => [`ml-engine/${file}`, hash]),
  ];
  for (const arm of ['v1-refit-control', 'typed-v2']) {
    const armAssessments = [];
    for (const [id, label, file, record, scope, cohort] of [
      ['regression', 'Reused regression test', `${EXTRACTOR}/regression-test-evaluation.json`, v2Final.arms[arm],
        'Eight known pairs / F005 and F010; inspected during representation design. Not unseen data.', 'synthetic-F005-F010-8'],
      ['validation', 'Validation diagnostic', `${EXTRACTOR}/validation-evaluation.json`, v2Validation[arm],
        'Eight F004/F009 pairs; fixed setting, no selection from validation results.', 'synthetic-F004-F009-8'],
      ['oof', 'Grouped out-of-fold', `${EXTRACTOR}/grouped-oof-evaluation.json`, v2Oof[arm],
        '24 pairs / six source families; each outer member fits four families, with inner out-of-family stacking.', 'synthetic-development-24'],
    ]) {
      const current = await assessment({ id, label, file, scope, cohort, reused: true, bindings: v2Bindings,
        data: { ...record.reviewTriageIncludingAbstentions, localization: record.localizationWeakLabels },
        notes: ['Review triage includes abstentions. Covered-only classifier metrics remain separate.',
          'Fixed C=0.1 and threshold=0.25 before results; no full-development refit.', 'Weak localization labels are exploratory.'] });
      current.coverage = record.coverage;
      current.classifierOnly = { metrics: metrics(record.coveredClassifierOnly), pairs: record.coveredClassifierOnly.pairs,
        confusion: record.coveredClassifierOnly.confusion };
      current.baselines = Object.entries(record.constantBaselines).map(([baseline, values]) => ({ id: baseline,
        metrics: metrics({ ...values, reviewWorkload: values.reviewWorkloadFraction, missedDefects: values.nonFlaggedDefects }),
        pairs: values.pairs, confusion: values.confusion }));
      current.perFamily = record.perFamily;
      armAssessments.push(current);
    }
    versions.push({
      id: `defect-${arm}`, name: arm === 'typed-v2' ? 'Defect V2 · typed extraction' : 'V1 refit · matched control',
      task: 'defect', status: 'experimental', threshold: v2Protocol.operatingThreshold, defaultAssessmentId: 'regression',
      summary: arm === 'typed-v2' ? 'Typed source-bound intermediate representation feeding the same regularized logistic architecture.'
        : 'Original extractor refitted under the V2 protocol to separate fitting changes from representation changes.',
      changes: arm === 'typed-v2'
        ? ['Preserves multiline expressions, operand order, numeric types, rounding, control flow, and output dependencies.',
          'Unsupported parsing abstains and requires review.', 'Name-independent structural signatures and adjacent dependency regions.']
        : ['Same C, threshold, folds, scaling and nested ranker stacking as typed V2.', 'Original heuristic extraction retained.'],
      problems: arm === 'typed-v2'
        ? ['Regression accuracy remains 4/8; the wrong cash denomination is still missed.', 'Compact features remain lossy; source coverage is not compiler correctness.',
          'The reused two-family test cannot establish generalization.']
        : ['No strict parse coverage guarantee.', 'Misses the same cash-denomination defect; 75% review workload on the regression split.'],
      nextSteps: ['Normalize currency units and compare receiving-field behavior.', 'Benchmark stronger tabular classifiers under a fresh family-level split.'],
      source: armAssessments[0].source, assessments: armAssessments,
    });
  }

  const matchingNote = 'Retrieves the corresponding program from a gallery. These labels do not measure defects or behavioral equivalence.';
  const matchingLimitations = ['143 small HumanEval-derived COBOL/Java pairs, not production banking migrations.',
    'All 23 later evaluation tasks were previously evaluated; later comparisons are descriptive.',
    'The name-matching baseline is much stronger on this named benchmark.', 'Similarity is not a correctness probability.'];
  const matchingModel = 'ml-engine/ml_engine/models/paired_program_gnn_v1.json';
  const matchingV1Bindings = [[matchingModel, v1Matching.modelSha256]];
  const matchingV1Assessments = [];
  for (const [id, label, values, scope] of [
    ['regression', 'Original 29-task test', v1Matching.evaluation.test.gnn, 'Original gallery of 29 candidates; not directly comparable with a 23-candidate gallery.'],
    ['shared-23', 'Shared 23-task comparison', matchingV2.metrics.previousV1Gnn, 'Pinned V1 model scored on the same 23-task gallery used in later experiments.'],
    ['validation', 'Original 29-task validation', v1Matching.evaluation.validation.gnn, 'Validation used for epoch selection; gallery contains 29 candidates.'],
  ]) {
    const file = id === 'shared-23' ? `${MATCHING}/cv-v2/final-evaluation-report.json` : `${MATCHING}/training-report.json`;
    const expected = id === 'shared-23' ? (await load(`${MATCHING}/cv-v2/deployment-manifest.json`)).finalEvaluationReportSha256
      : matchingV2.priorExposure.priorReportSha256;
    matchingV1Assessments.push(await assessment({ id, label, data: values, file, expected,
      bindings: matchingV1Bindings, scope, cohort: id === 'shared-23' ? 'humaneval-shared-23' : `humaneval-v1-${id}-29`,
      reused: true, notes: [matchingNote] }));
  }
  versions.push({ id: 'matching-v1', name: 'Program matching V1 · paired GNN', task: 'matching', status: 'historical',
    summary: 'Shared graph encoder trained with contrastive correspondence learning on 85 fitting pairs.',
    changes: ['Removed identifiers, comments and method names from learned features.', 'Epoch selected using 29 validation pairs.'],
    problems: matchingLimitations, nextSteps: ['Use matching as navigation; measure defect detection separately.'],
    defaultAssessmentId: 'shared-23', source: matchingV1Assessments.find(item => item.id === 'shared-23').source, assessments: matchingV1Assessments });

  for (const [id, directory, finalReport, modelFile, name, summary] of [
    ['matching-v2', 'cv-v2', matchingV2, 'paired_program_gnn_v2_cv.json', 'Program matching V2 · CV + full refit',
      'Five-fold epoch selection on 120 development pairs, followed by a full 120-pair refit.'],
    ['matching-v3', 'cv-v3-fold-ensemble', matchingV3, 'paired_program_gnn_v3_fold_ensemble.json', 'Program matching V3 · fold ensemble',
      'Retains five fold checkpoints; each member fits 96 pairs. No member is refitted on all 120.'],
  ]) {
    const base = `${MATCHING}/${directory}`;
    const [deployment, freeze, training] = await Promise.all([load(`${base}/deployment-manifest.json`), load(`${base}/model-freeze.json`), load(`${base}/cv-training-report.json`)]);
    const bindings = [[`ml-engine/ml_engine/models/${modelFile}`, deployment.modelSha256],
      [`${base}/model-freeze.json`, finalReport.freezeSha256],
      ...Object.entries(freeze.files).map(([file, hash]) => [`${base}/${file}`, hash])];
    const finalAssessment = await assessment({ id: 'regression', label: 'Reused 23-task gallery', scope: '23 original source tasks; each query ranks the same 23 candidates.',
      cohort: 'humaneval-shared-23', reused: true, data: finalReport.metrics.gnn, file: `${base}/final-evaluation-report.json`,
      expected: deployment.finalEvaluationReportSha256, bindings,
      notes: [matchingNote, 'Excluded from this fit, but previously evaluated in earlier versions.'] });
    finalAssessment.baselines = ['noMessagePassing', 'nameMatching', 'semanticHistogram'].map(key => ({ id: key, metrics: metrics(finalReport.metrics[key]) }));
    const oofAssessment = await assessment({ id: 'oof', label: 'Five-fold selection scores', scope: '120 designated held-out queries; each gallery has 24 candidates. Selection evidence, not nested CV or ensemble validation.',
      cohort: 'humaneval-development-120-gallery24', reused: true, data: training.selection.gnn.pooledMetrics,
      file: `${base}/cv-training-report.json`, expected: freeze.files['cv-training-report.json'], bindings,
      notes: ['One held-out member scores each query; other ensemble members trained on it.', matchingNote] });
    versions.push({ id, name, task: 'matching', status: 'historical', summary,
      changes: id === 'matching-v2' ? ['Five-fold development selection.', 'Full-development refit after selecting epoch.']
        : ['Equal-mean cosine ensemble of five fold models.', 'No full-development refit.'],
      problems: [...matchingLimitations, 'These experiments do not isolate refitting as the cause of any performance difference.',
        ...(id === 'matching-v2' ? ['Historical protocol retained a full 120-pair refit; superseded when the project required fold models without a full-development refit.'] : [])],
      nextSteps: ['Collect fresh tasks with changed naming and production-style contracts.'], defaultAssessmentId: 'regression',
      source: finalAssessment.source, assessments: [finalAssessment, oofAssessment] });
  }

  const v4Base = `${MATCHING}/cv-v4-candidates`;
  const [v4Freeze, v4Deployment] = await Promise.all([load(`${v4Base}/model-freeze.json`), load(`${v4Base}/deployment-manifest.json`)]);
  const candidateNames = { baseline: 'V4 baseline · paired GNN ensemble', structural_cca: 'V4 structural CCA · graph features',
    graph_regularized: 'V4 graph regularization · selected', language_heads: 'V4 separate language heads', count_readout: 'V4 count-aware readout' };
  const candidateSummaries = {
    baseline: 'Unmodified five-member paired GNN ensemble; control for four research adaptations.',
    structural_cca: 'Hashed relation-aware Weisfeiler–Lehman counts plus fold-local regularized linear CCA.',
    graph_regularized: 'Paired GNN with 10% auxiliary sequence-edge dropout during fitting; data/control edges retained.',
    language_heads: 'Shared graph backbone with separate COBOL and Java projection heads, trained with InfoNCE.',
    count_readout: 'Mean, max and scaled-sum readouts with explicit node count features.',
  };
  for (const candidate of Object.keys(candidateNames)) {
    const selected = candidate === matchingV4.cvWinner;
    const bindings = [[`${v4Base}/model-freeze.json`, matchingV4.freezeSha256],
      [`${v4Base}/frozen-${candidate}.json`, v4Freeze.files[`frozen-${candidate}.json`]],
      [`${v4Base}/cv-training-report.json`, v4Freeze.files['cv-training-report.json']],
      ...(selected ? [['ml-engine/ml_engine/models/paired_program_v4_selected.json', v4Deployment.modelSha256]] : [])];
    const finalAssessment = await assessment({ id: 'regression', label: 'Reused 23-task gallery', scope: 'Same known 23 source tasks and candidates; descriptive comparison after earlier exposure.',
      cohort: 'humaneval-shared-23', reused: true, data: matchingV4.metrics[candidate], file: `${v4Base}/final-evaluation-report.json`,
      expected: v4Deployment.finalEvaluationReportSha256, bindings,
      notes: [matchingNote, 'Deployment follows the development-CV winner, regardless of the higher language-head final score.'] });
    finalAssessment.baselines = ['nameMatching', 'semanticHistogram'].map(key => ({ id: key, metrics: metrics(matchingV4.metrics[key]) }));
    const oofAssessment = await assessment({ id: 'oof', label: 'Five-fold selection scores', scope: v4Training.scope,
      cohort: 'humaneval-development-120-gallery24', reused: true, data: v4Training.selections[candidate].pooledMetrics,
      file: `${v4Base}/cv-training-report.json`, expected: v4Freeze.files['cv-training-report.json'], bindings,
      notes: ['120 development queries / 24-candidate galleries. Every learned statistic uses only the 96 fitting pairs in its fold.',
        'Development scores selected architecture and epoch; not unbiased nested-CV performance.'] });
    versions.push({ id: `matching-v4-${candidate}`, name: candidateNames[candidate], task: 'matching', status: selected ? 'deployed' : 'experimental',
      summary: candidateSummaries[candidate], changes: [candidateSummaries[candidate], 'Five fold members; no 120-pair full-development refit.'],
      problems: [...matchingLimitations, ...(candidate === 'language_heads'
        ? ['Highest final Top-1 among V4 candidates, but it was not the pre-frozen CV winner. Switching from this report would leak evaluation results into selection.'] : [])],
      nextSteps: ['Validate on independent translation families; retain the frozen CV selection rule.'],
      selectedByDevelopmentCv: selected, defaultAssessmentId: 'regression', source: finalAssessment.source,
      papers: v4Plan.papers[candidate] ? [v4Plan.papers[candidate]] : [], assessments: [finalAssessment, oofAssessment] });
  }

  const dataset = await load(DATASET);
  const family = dataset.families.find(item => item.familyId === 'F005');
  const variant = family.variants.find(item => item.variantId === 'F005-V4');
  const [auditReport, auditHashes, sourceHashes] = await Promise.all([load(`${AUDIT}/report.json`), load(`${AUDIT}/artifact-hashes.json`), load(`${AUDIT}/source-hashes.json`)]);
  const cobolCode = family.cobolLines.join('\n'), javaCode = variant.javaLines.join('\n');
  const witness = auditReport.cases.find(item => item.testId === 'F005-R2-T2');
  const javaWitness = witness.variants.find(item => item.variantId === variant.variantId);
  const evidence = await source(`${AUDIT}/report.json`, auditHashes['report.json'],
    [[`${AUDIT}/source-hashes.json`, auditHashes['source-hashes.json']], [DATASET, v2Freeze.datasetSha256]]);
  evidence.checks.push(
    { path: 'F005 COBOL source string', expectedSha256: sourceHashes.F005.cobol, actualSha256: digest(cobolCode), verified: digest(cobolCode) === sourceHashes.F005.cobol },
    { path: 'F005-V4 Java source string', expectedSha256: sourceHashes.F005.java['F005-V4'], actualSha256: digest(javaCode), verified: digest(javaCode) === sourceHashes.F005.java['F005-V4'] });
  evidence.integrity = evidence.checks.every(check => check.verified) ? 'verified' : 'unverified';
  const caseStudy = {
    id: variant.variantId, title: 'A real executed mismatch the model still misses',
    summary: 'Synthetic translation with an observed runtime defect: Java changes five-cent cash rounding to ten-cent rounding.',
    datasetKind: dataset.datasetKind, cobolCode, javaCode,
    culprit: { language: 'java', startLine: 9, endLine: 9, reason: variant.labelRationale },
    correspondingCobol: { startLine: 21, endLine: 21 },
    witness: { testId: witness.testId, stdin: witness.stdin,
      inputs: witness.stdin.trimEnd().split('\n'), cobolOutput: witness.observedReferenceValue,
      javaOutput: javaWitness.observedValue, expectedOutput: witness.observedReferenceValue,
      rawCobolOutput: witness.referenceRun.stdout, rawJavaOutput: javaWitness.run.stdout,
      mismatch: javaWitness.observedMismatch,
      explanation: '12.34 × 1.2500 = 15.425; cent rounding gives 15.43. Five-cent cash rounding gives 15.45; ten-cent rounding gives 15.40.',
      recordedAt: auditReport.checkedAtUtc, executedNow: false },
    evidence,
    modelFindings: [
      { versionId: 'defect-v1', ...v1Final.predictions.find(item => item.variantId === variant.variantId) },
      ...['v1-refit-control', 'typed-v2'].map(arm => ({ versionId: `defect-${arm}`,
        ...v2Final.arms[arm].predictions.find(item => item.variantId === variant.variantId) })),
    ],
    limitations: ['Finite offline runtime witness, not a universal equivalence proof.',
      'The red line is the recorded curation annotation; it is not claimed as a successful model localization.',
      'No uploaded source code is executed by this benchmark site.'],
  };
  const contractSource = await source(`${EXTRACTOR}/contract-diagnostics.json`, v2Freeze.contractAuditSha256,
    Object.entries(v2Freeze.implementationHashes).map(([file, hash]) => [`ml-engine/${file}`, hash]));
  return {
    schemaVersion: 1, generatedAt,
    repository: { url, branch, branchUrl, commit, commitUrl }, versions,
    contracts: { fixtureCount: v2Contracts.fixtureCount, passed: v2Contracts.passedContracts,
      failed: v2Contracts.failedContracts, scope: v2Contracts.artifact, source: contractSource,
      codeExecuted: v2Contracts.codeExecuted, modelTrained: v2Contracts.modelTrained,
      results: v2Contracts.results,
      note: 'Eight representation contracts passed. This is extraction evidence, not eight accuracy samples or compiler validation.',
      abandonedAudit: { path: 'ml-engine/evaluation/extractor-v2/pilot-r1/contract-diagnostics.json',
        status: 'Pre-fit audit; no trained R1 version. Its issue was corrected before the R2 experiment.' } },
    caseStudy,
    methodology: { readOnly: true, inferencePerformed: false, trainingPerformed: false,
      metricUnits: 'Fractions in [0,1], except missedDefects which is a count; missing metrics are null.',
      acceptanceAuthority: false,
      warnings: ['Defect classification and program retrieval are different tasks. Never compare their scores as one accuracy measure.',
        'Later evaluation cohorts are reused, not pristine unseen data.', 'A recorded hash match establishes artifact consistency, not model validity.',
        'No current ML model may approve a translation.'] },
  };
}
