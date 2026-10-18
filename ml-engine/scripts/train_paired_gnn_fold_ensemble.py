#!/usr/bin/env python3
"""Retain five grouped-CV checkpoints; never refit on all 120 development pairs.

Run --prepare, --train, then --evaluate-final. One epoch is selected from pooled
out-of-fold development results. The five corresponding 96-pair checkpoints
form a fixed equal-mean cosine ensemble. The unchanged final 23 tasks are never
used for fitting or selection in this run. They were exposed in earlier runs;
this experiment therefore cannot establish performance on pristine unseen data.
"""
from __future__ import annotations

import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml_engine.code_graph import FEATURE_NAMES, RELATIONS
from ml_engine.paired_gnn import backward, batch_graphs, forward, initialise, paired_loss
from scripts.train_paired_gnn_cv import (
    FIXED_GATE, LIMITATIONS as V2_LIMITATIONS, adam_step, baseline_scores,
    canonical_bytes, checkpoint_epochs, graph_pairs, load_dataset, per_query_result,
    prior_exposure as v1_prior_exposure, rank_metrics, ranks_from_scores, read_json,
    score_model, select_epoch, sha256_bytes, sha256_file, summarise_folds,
    utc_now, validate_partition, write_json,
)

MODEL_ID = 'paired-program-gnn-v3-fold-ensemble'
DEFAULT_OUTPUT = ROOT / 'evaluation/paired-code/cv-v3-fold-ensemble'
DEFAULT_MODEL = ROOT / 'ml_engine/models/paired_program_gnn_v3_fold_ensemble.json'
PREVIOUS_MODELS = {
    'previousV1Gnn': ROOT / 'ml_engine/models/paired_program_gnn_v1.json',
    'previousV2Gnn': ROOT / 'ml_engine/models/paired_program_gnn_v2_cv.json',
}
LIMITATIONS = [
    *V2_LIMITATIONS,
    'All final 23 tasks were previously evaluated in v1 and v2. The no-refit protocol was requested after those results were visible; this final comparison is descriptive, not a new unbiased validation.',
    'A fixed equal-mean cosine ensemble retains all five CV checkpoints. No individual fold, ensemble weight, aggregation rule, seed or epoch is selected using final-holdout results.',
    'Each retained member fits 96 development pairs. Across the five members all 120 development pairs are used, but no member is fitted or refitted on all 120.',
    'Pooled out-of-fold metrics describe one held-out member per development query; they do not estimate the deployed five-member ensemble, whose other members saw that development query.',
    'These experiments do not isolate or prove that the v2 full-development refit caused a change in generalization or weight variance.',
]


def source_hashes() -> dict[str, str]:
    paths = [Path(__file__), ROOT / 'scripts/train_paired_gnn_cv.py',
             ROOT / 'ml_engine/code_graph.py', ROOT / 'ml_engine/paired_gnn.py',
             ROOT / 'scripts/train_paired_gnn.py', ROOT / 'ml_engine/cv_partition.py',
             ROOT / 'scripts/partition_paired_dataset.py']
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in paths}


def prior_exposure(partition: dict) -> dict:
    exposure = v1_prior_exposure(partition)
    exposure.update({
        'previouslyEvaluatedByV2': True,
        'previousV2ReportSha256': sha256_file(ROOT / 'evaluation/paired-code/cv-v2/final-evaluation-report.json'),
        'protocolChangedAfterExposure': True,
        'limitation': 'The same final 23 were evaluated in both v1 and v2. They remain excluded from every new fit and CV choice, but are previously exposed evaluation tasks, not new unforeseen data. The user-requested no-refit comparison is descriptive.',
    })
    return exposure


def fit_fold_checkpoints(graphs: tuple[list, list], train_indices: list[int],
                         validation_indices: list[int], *, seed: int, epochs: int,
                         message_passing: bool) -> tuple[list[dict], dict[int, dict]]:
    """Fresh fit of one disjoint fold, retaining copies only at fixed checkpoints.

    Checkpoints remain in memory until the common development-only epoch is
    selected; only the selected five member states are persisted to the artifact.
    """
    if not train_indices or len(set(train_indices)) != len(train_indices):
        raise ValueError('Unique nonempty fitting indices are required.')
    if (not validation_indices or len(set(validation_indices)) != len(validation_indices)
            or set(train_indices) & set(validation_indices)):
        raise ValueError('Fitting and validation indices must be nonempty, unique and disjoint.')
    checkpoints_at = set(checkpoint_epochs(epochs))
    fitting = [batch_graphs([side[index] for index in train_indices], message_passing) for side in graphs]
    validation = [batch_graphs([side[index] for index in validation_indices], message_passing) for side in graphs]
    params = initialise(seed)
    first = {name: np.zeros_like(value) for name, value in params.items()}
    second = {name: np.zeros_like(value) for name, value in params.items()}
    history, checkpoints = [], {}
    for epoch in range(1, epochs + 1):
        cobol, cache_cobol = forward(fitting[0], params, True)
        java, cache_java = forward(fitting[1], params, True)
        loss, dc, dj = paired_loss(cobol, java)
        gc, gj = backward(dc, cache_cobol, params), backward(dj, cache_java, params)
        adam_step(params, first, second, {name: gc[name] + gj[name] for name in params}, epoch)
        if epoch in checkpoints_at:
            cv, jv = [forward(batch, params) for batch in validation]
            ranks = ranks_from_scores(cv @ jv.T)
            history.append({'epoch': epoch, 'trainLoss': float(loss),
                            'validationLoss': float(paired_loss(cv, jv)[0]),
                            'ranks': ranks, **rank_metrics(ranks, len(ranks))})
            checkpoints[epoch] = {name: value.copy() for name, value in params.items()}
    return history, checkpoints


def score_ensemble(graphs: tuple[list, list], members: list[dict],
                   message_passing: bool = True) -> np.ndarray:
    """Mean separately normalized member cosine scores; never average weights."""
    if not members:
        raise ValueError('At least one ensemble member is required.')
    scores = []
    for member in members:
        params = {name: np.asarray(value, dtype=float) for name, value in member['weights'].items()}
        scores.append(score_model(graphs, params, message_passing))
    return np.mean(scores, axis=0)


def verify_run_plan(args: argparse.Namespace) -> tuple[dict, dict, list[dict], dict]:
    run_plan = read_json(args.output_dir / 'run-plan.json')
    partition = read_json(args.partition_plan)
    rows, manifest = load_dataset(args.dataset)
    validate_partition(partition, rows, manifest['sha256'])
    if run_plan['partitionPlanSha256'] != sha256_file(args.partition_plan):
        raise ValueError('Partition plan changed after preparation.')
    if run_plan['sourceSha256'] != source_hashes():
        raise ValueError('Trainer/encoder code changed after preparation; preserve this run and declare a new experiment.')
    for relative, expected in run_plan['sourceSha256'].items():
        if sha256_file(args.output_dir / 'source-snapshot' / relative) != expected:
            raise ValueError('Prepared source snapshot changed: ' + relative)
    if run_plan['datasetSha256'] != manifest['sha256']:
        raise ValueError('Prepared dataset mismatch.')
    if (run_plan['configuration']['epochsBudget'] != args.epochs
            or run_plan['configuration']['seed'] != args.seed):
        raise ValueError('Epoch budget/seed differs from frozen run plan.')
    for label, path in PREVIOUS_MODELS.items():
        if sha256_file(path) != run_plan['previousModels'][label]['sha256']:
            raise ValueError('Pinned historical baseline changed after preparation: ' + label)
    return run_plan, partition, rows, manifest


def prepare(args: argparse.Namespace) -> dict:
    if (args.output_dir / 'run-plan.json').exists():
        raise ValueError('A run plan already exists. Preserve its audit trail; use a new output directory for another experiment.')
    rows, manifest = load_dataset(args.dataset)
    partition = read_json(args.partition_plan)
    validate_partition(partition, rows, manifest['sha256'])
    if partition['seed'] != args.seed:
        raise ValueError('Run seed must match partition seed.')
    frozen_sources = source_hashes()
    for relative, digest in frozen_sources.items():
        raw = (ROOT / relative).read_bytes()
        if sha256_bytes(raw) != digest:
            raise ValueError('Source changed while preparing its immutable snapshot: ' + relative)
        destination = args.output_dir / 'source-snapshot' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write(raw)
    plan = {
        'schemaVersion': 1, 'modelId': MODEL_ID, 'createdAt': utc_now(),
        'datasetSha256': manifest['sha256'], 'partitionPlanSha256': sha256_file(args.partition_plan),
        'sourceSha256': frozen_sources, 'sourceSnapshotDirectory': 'source-snapshot',
        'numpyVersion': np.__version__,
        'partitionPlanUse': {
            'assignments': 'Reuse the unchanged score-independent graph components, 120/23 membership and five 96/24 folds.',
            'supersededPolicy': partition.get('selectionProtocol'),
            'policyOverride': 'The frozen partition plan also records the historical v2 full-development-refit policy. This v3 run reuses assignments only and explicitly supersedes that policy: retain the five selected fold checkpoints and never fit/refit any member on all 120.',
            'fullDevelopmentRefit': False,
        },
        'previousModels': {label: {
            'id': read_json(path)['id'], 'sha256': sha256_file(path), 'path': str(path.relative_to(ROOT)),
            'purpose': 'Frozen descriptive baseline on the same 23-task gallery; never used for any selection.',
        } for label, path in PREVIOUS_MODELS.items()},
        'configuration': {
            'seed': args.seed, 'epochsBudget': args.epochs, 'checkpointEpochs': checkpoint_epochs(args.epochs),
            'foldCount': 5, 'developmentTasks': 120, 'finalHoldoutTasks': 23,
            'foldTrainingTasks': 96, 'foldValidationTasks': 24,
            'initialization': 'Fresh parameters and fresh Adam state for every fold and ablation; same declared seed.',
            'architecture': 'Unchanged two-layer relation-aware GNN; hidden/output 24; shared COBOL/Java encoder.',
            'optimizer': {'name': 'Adam', 'learningRate': .004, 'beta1': .9, 'beta2': .999,
                          'epsilon': 1e-8, 'weightDecay': .0001, 'gradientClip': 5},
            'objective': 'Symmetric paired-source InfoNCE, temperature 0.12; negatives only from the current 96-pair fitting fold.',
            'selection': 'One common epoch selected by pooled 120 out-of-fold reciprocal ranks (MRR), then query-weighted validation loss, then earliest checkpoint. No final-set selection.',
            'ablation': 'Five no-message members with identical capacity, fresh seed, optimizer, epoch budget and folds; its own same pooled-OOF epoch rule.',
            'ensemble': {'aggregation': 'MEAN_COSINE', 'members': 5,
                         'weights': [.2] * 5, 'selection': 'Retain every fold at the common selected epoch; no best-fold selection.'},
            'fullDevelopmentRefit': False,
            'thresholds': FIXED_GATE,
            'ties': 'Stable candidate order saved in the frozen partition plan.',
            'finalProtocol': 'Freeze both five-member ensembles, selected epochs, gate and CV report before any learned encoding/scoring of the final 23. One final evaluation per frozen run. All final scores use the declared mean of member cosine similarities.',
            'prohibited': ['No model fit or refit on all 120 development pairs.',
                           'No final-holdout graphs/embeddings/loss/negative gallery in fitting, CV or selection.',
                           'No architecture, augmentation, loss, seed, threshold or aggregation search.',
                           'No fold selection, parameter averaging, or embedding averaging.'],
        },
        'priorExposure': prior_exposure(partition), 'limitations': LIMITATIONS,
    }
    plan['runId'] = 'paired-cv-v3-ensemble-' + sha256_bytes(canonical_bytes(plan))[:16]
    digest = write_json(args.output_dir / 'run-plan.json', plan)
    return {'stage': 'PREPARED', 'runId': plan['runId'], 'runPlanSha256': digest,
            'counts': {'development': 120, 'finalHoldout': 23, 'folds': 5}, 'fullDevelopmentRefit': False}


def make_model(members: list[dict], run_plan: dict, manifest: dict, selection: dict,
               no_selection: dict, *, message_passing: bool = True) -> dict:
    if len(members) != 5:
        raise ValueError('Exactly five retained CV members are required.')
    return {
        'id': MODEL_ID if message_passing else 'paired-program-no-message-v3-fold-ensemble',
        'kind': 'FOLD_ENSEMBLE',
        'architecture': 'Five separately fitted two-layer relation-aware GNNs; fixed mean of member cosine similarities'
                        + ('' if message_passing else '; relation edges removed for ablation'),
        'messagePassing': message_passing,
        'featureNames': list(FEATURE_NAMES), 'relations': list(RELATIONS),
        'ensemble': {'aggregation': 'MEAN_COSINE', 'members': 5}, 'members': members,
        'training': {
            'dataset': 'COBOL-JavaTrans (143 original source pairs; 120 development / 23 final fitting holdout)',
            'datasetSha256': manifest['sha256'], 'sourceCommit': manifest['commit'],
            'seed': run_plan['configuration']['seed'], 'epochsBudget': run_plan['configuration']['epochsBudget'],
            'selectedEpoch': selection['selectedEpoch'], 'noMessageSelectedEpoch': no_selection['selectedEpoch'],
            'objective': 'symmetric paired-source InfoNCE; temperature0.12; Adam0.004; weight decay0.0001',
            'splitCounts': {'development': 120, 'finalHoldout': 23},
            'crossValidation': {'folds': 5, 'trainPerFold': 96, 'validationPerFold': 24,
                                'selectedPooledOutOfFoldMetrics': selection['pooledMetrics']},
            'selection': run_plan['configuration']['selection'], 'fullDevelopmentRefit': False,
            'retainedFoldCheckpoints': 5, 'ensembleAggregation': 'MEAN_COSINE',
            'featureLeakageControls': ['identifier spelling excluded', 'comments excluded', 'program/method/task names excluded', 'whole related-task graph components kept together before fitting'],
        },
        'thresholds': copy.deepcopy(FIXED_GATE),
        'evaluation': {'status': 'FROZEN_AWAITING_FINAL_EVALUATION', 'test': {'status': 'NOT_EVALUATED'},
                       'validation': {'gnn' if message_passing else 'noMessagePassing': selection['pooledMetrics']},
                       'financialDomainValidated': False,
                       'scope': 'whole-program paired-task retrieval, not statement localization or formal equivalence'},
        'limitations': LIMITATIONS,
        'provenance': {'dataset': manifest, 'trainedOn': datetime.now(timezone.utc).date().isoformat(),
                       'runId': run_plan['runId'], 'partitionPlanSha256': run_plan['partitionPlanSha256'],
                       'generatedBy': 'AI-assisted implementation; actual CPU fitting on pinned paired source',
                       'finalHoldoutPriorExposure': run_plan['priorExposure']},
    }


def retained_members(folds: list[dict], checkpoints: list[dict], selected_epoch: int) -> list[dict]:
    return [{
        'fold': fold['fold'], 'trainingTaskIds': fold['trainTaskIds'],
        'validationTaskIds': fold['candidateOrder'], 'selectedEpoch': selected_epoch,
        'weights': {name: value.round(12).tolist() for name, value in states[selected_epoch].items()},
    } for fold, states in zip(folds, checkpoints)]


def train(args: argparse.Namespace) -> dict:
    if (args.output_dir / 'model-freeze.json').exists() or (args.output_dir / 'final-evaluation-started.json').exists():
        raise ValueError('This declared run is already frozen/evaluated; refuse retraining over its audit trail.')
    started = time.monotonic()
    run_plan, partition, rows, manifest = verify_run_plan(args)
    with (args.output_dir / 'training-started.json').open('x') as handle:
        json.dump({'runId': run_plan['runId'], 'startedAt': utc_now(),
                   'note': 'Exclusive marker; no 120-pair refit is permitted.'}, handle, indent=2)
        handle.write('\n')
    by_id = {row['task_id']: row for row in rows}
    development_ids = partition['developmentTaskIds']
    development_rows = [by_id[identifier] for identifier in development_ids]
    # Final-holdout sources do not enter learned graph batches or any fold.
    graphs = graph_pairs(development_rows)
    index = {identifier: i for i, identifier in enumerate(development_ids)}
    folds_by_model = {'gnn': [], 'noMessagePassing': []}
    checkpoint_states = {'gnn': [], 'noMessagePassing': []}
    baseline_folds = []
    for fold in partition['folds']:
        train_indices = [index[identifier] for identifier in fold['trainTaskIds']]
        validation_indices = [index[identifier] for identifier in fold['validationTaskIds']]
        if len(train_indices) != 96 or len(validation_indices) != 24:
            raise ValueError('Training must use precisely the declared 96/24 folds.')
        for label, use_messages in (('gnn', True), ('noMessagePassing', False)):
            history, states = fit_fold_checkpoints(graphs, train_indices, validation_indices,
                                                 seed=args.seed, epochs=args.epochs, message_passing=use_messages)
            folds_by_model[label].append({'fold': fold['fold'], 'trainTaskIds': fold['trainTaskIds'],
                                         'candidateOrder': fold['validationTaskIds'], 'history': history})
            checkpoint_states[label].append(states)
            print(json.dumps({'stage': 'CV_FOLD_COMPLETE', 'model': label, 'fold': fold['fold'],
                              'epochsBudget': args.epochs, 'trainingTasks': 96, 'validationTasks': 24,
                              'checkpointsRetainedInMemory': len(states)}), flush=True)
        selected_graphs = tuple([side[i] for i in validation_indices] for side in graphs)
        selected_rows = [development_rows[i] for i in validation_indices]
        baseline_folds.append({'fold': fold['fold'], **{
            label: per_query_result(scores, fold['validationTaskIds'])
            for label, scores in baseline_scores(selected_rows, selected_graphs).items()}})
    selections = {label: select_epoch([fold['history'] for fold in folds]) for label, folds in folds_by_model.items()}
    for label, folds in folds_by_model.items():
        for fold in folds:
            selected = next(record for record in fold['history'] if record['epoch'] == selections[label]['selectedEpoch'])
            fold['selectedCheckpointPerQuery'] = [
                {'taskId': identifier, 'correctCandidateTaskId': identifier, 'rank': rank, 'reciprocalRank': 1 / rank}
                for identifier, rank in zip(fold['candidateOrder'], selected['ranks'])]
    models = {}
    for label, use_messages in (('gnn', True), ('noMessagePassing', False)):
        members = retained_members(folds_by_model[label], checkpoint_states[label], selections[label]['selectedEpoch'])
        models[label] = make_model(members, run_plan, manifest, selections[label], selections['noMessagePassing'],
                                   message_passing=use_messages)
    report = {
        'modelId': MODEL_ID, 'runId': run_plan['runId'], 'createdAt': utc_now(),
        'runPlanSha256': sha256_file(args.output_dir / 'run-plan.json'),
        'partitionPlanSha256': run_plan['partitionPlanSha256'], 'datasetSha256': manifest['sha256'],
        'developmentTasks': 120, 'finalHoldoutTasksNeverLearnedEncodedOrScoredAtThisStage': 23,
        'fullDevelopmentRefit': False,
        'retainedCheckpoints': {'gnn': 5, 'noMessagePassing': 5},
        'ensemble': run_plan['configuration']['ensemble'],
        'partitionInspectionNote': 'Deterministic graph partitioning inspected all tasks to prevent related-task leakage; no final source graph enters learned fitting, CV or selection.',
        'selection': selections, 'folds': folds_by_model,
        'foldSummary': {label: summarise_folds(folds, selections[label]['selectedEpoch']) for label, folds in folds_by_model.items()},
        'outOfFoldScope': 'Each development query is evaluated by the one member that excluded its fold; these are not five-member ensemble validation metrics.',
        'baselineFolds': baseline_folds,
        'baselinePooledMetrics': {label: rank_metrics([query['rank'] for fold in baseline_folds for query in fold[label]['queries']], 24)
                                  for label in ('nameMatching', 'semanticHistogram')},
        'thresholds': FIXED_GATE, 'priorExposure': run_plan['priorExposure'], 'limitations': LIMITATIONS,
        'durationSeconds': round(time.monotonic() - started, 3),
    }
    report_hash = write_json(args.output_dir / 'cv-training-report.json', report)
    model_hash = write_json(args.output_dir / 'frozen-checkpoint.json', models['gnn'], compact=True)
    no_hash = write_json(args.output_dir / 'frozen-no-message-checkpoint.json', models['noMessagePassing'], compact=True)
    freeze = {
        'schemaVersion': 1, 'runId': run_plan['runId'], 'frozenAt': utc_now(),
        'runPlanSha256': sha256_file(args.output_dir / 'run-plan.json'),
        'partitionPlanSha256': sha256_file(args.partition_plan), 'sourceSha256': source_hashes(),
        'datasetSha256': manifest['sha256'], 'fullDevelopmentRefit': False,
        'gnnMembersSha256': sha256_bytes(canonical_bytes(models['gnn']['members'])),
        'noMessageMembersSha256': sha256_bytes(canonical_bytes(models['noMessagePassing']['members'])),
        'files': {'frozen-checkpoint.json': model_hash, 'frozen-no-message-checkpoint.json': no_hash,
                  'cv-training-report.json': report_hash},
        'selectedEpoch': selections['gnn']['selectedEpoch'],
        'noMessageSelectedEpoch': selections['noMessagePassing']['selectedEpoch'],
        'ensemble': {'aggregation': 'MEAN_COSINE', 'members': 5}, 'thresholds': FIXED_GATE,
        'previousModelSha256': {label: row['sha256'] for label, row in run_plan['previousModels'].items()},
        'finalHoldoutLearnedEncodingOrScoringPerformed': False,
        'finalEvaluationRule': 'One evaluation of frozen ensembles and fixed historical baselines on the same 23-task gallery; no final-data selection or subsequent refit.',
    }
    freeze['freezeId'] = 'paired-cv-v3-ensemble-freeze-' + sha256_bytes(canonical_bytes(freeze))[:16]
    freeze_hash = write_json(args.output_dir / 'model-freeze.json', freeze)
    return {'stage': 'FROZEN', 'runId': run_plan['runId'], 'freezeId': freeze['freezeId'],
            'freezeSha256': freeze_hash, 'fullDevelopmentRefit': False,
            'selectedEpochs': {label: value['selectedEpoch'] for label, value in selections.items()},
            'cvPooledMetrics': {label: value['pooledMetrics'] for label, value in selections.items()},
            'durationSeconds': report['durationSeconds']}


def evaluate_final(args: argparse.Namespace) -> dict:
    if (args.output_dir / 'final-evaluation-report.json').exists():
        raise ValueError('Final evaluation already completed; inspect saved results rather than repeating the holdout.')
    run_plan, partition, rows, manifest = verify_run_plan(args)
    freeze_path = args.output_dir / 'model-freeze.json'
    freeze = read_json(freeze_path)
    if freeze['runId'] != run_plan['runId'] or freeze['runPlanSha256'] != sha256_file(args.output_dir / 'run-plan.json'):
        raise ValueError('Frozen checkpoint belongs to a different run plan.')
    if freeze['partitionPlanSha256'] != sha256_file(args.partition_plan) or freeze['sourceSha256'] != source_hashes():
        raise ValueError('Partition/encoder/trainer changed after freeze.')
    for name, expected in freeze['files'].items():
        if sha256_file(args.output_dir / name) != expected:
            raise ValueError('Frozen artifact changed: ' + name)
    model = read_json(args.output_dir / 'frozen-checkpoint.json')
    no_model = read_json(args.output_dir / 'frozen-no-message-checkpoint.json')
    if any(item['thresholds'] != FIXED_GATE for item in (model, no_model, freeze)):
        raise ValueError('Fixed human-review gate changed after preparation.')
    if any(item['fullDevelopmentRefit'] is not False for item in (model['training'], no_model['training'], freeze)):
        raise ValueError('A full-development refit violates this run protocol.')
    if (sha256_bytes(canonical_bytes(model['members'])) != freeze['gnnMembersSha256']
            or sha256_bytes(canonical_bytes(no_model['members'])) != freeze['noMessageMembersSha256']):
        raise ValueError('Frozen member weights or memberships changed.')
    for artifact in (model, no_model):
        if len(artifact['members']) != 5 or artifact['ensemble'] != {'aggregation': 'MEAN_COSINE', 'members': 5}:
            raise ValueError('Expected the frozen five-member mean-cosine ensemble.')
        for member, fold in zip(artifact['members'], partition['folds']):
            if (member['fold'] != fold['fold'] or member['trainingTaskIds'] != fold['trainTaskIds']
                    or member['validationTaskIds'] != fold['validationTaskIds']
                    or member['selectedEpoch'] != artifact['training']['selectedEpoch']):
                raise ValueError('Retained member differs from its declared 96/24 fold or common selected epoch.')
    if freeze['previousModelSha256'] != {label: value['sha256'] for label, value in run_plan['previousModels'].items()}:
        raise ValueError('Historical baseline pin differs from the frozen plan.')
    marker = {'runId': run_plan['runId'], 'freezeId': freeze['freezeId'], 'freezeSha256': sha256_file(freeze_path),
              'startedAt': utc_now(), 'warning': 'One-shot marker. Preserve even if scoring fails; never silently repeat or tune on these final tasks.'}
    with (args.output_dir / 'final-evaluation-started.json').open('x') as handle:
        json.dump(marker, handle, indent=2)
        handle.write('\n')
    by_id = {row['task_id']: row for row in rows}
    identifiers = partition['finalHoldoutTaskIds']
    final_rows = [by_id[identifier] for identifier in identifiers]
    graphs = graph_pairs(final_rows)
    # Cache each member's score matrix once. All displayed member metrics and
    # ensemble scores derive from these same matrices, without test-based choice.
    member_scores = {}
    for label, artifact, use_messages in (('gnn', model, True), ('noMessagePassing', no_model, False)):
        member_scores[label] = [score_model(graphs, {
            name: np.asarray(value, dtype=float) for name, value in member['weights'].items()
        }, use_messages) for member in artifact['members']]
    scores_by_model = {label: np.mean(scores, axis=0) for label, scores in member_scores.items()}
    scores_by_model.update(baseline_scores(final_rows, graphs))
    for label, path in PREVIOUS_MODELS.items():
        previous = read_json(path)
        params = {name: np.asarray(value, dtype=float) for name, value in previous['weights'].items()}
        scores_by_model[label] = score_model(graphs, params, True)
    results = {label: per_query_result(scores, identifiers) for label, scores in scores_by_model.items()}
    cv_report = read_json(args.output_dir / 'cv-training-report.json')
    report = {
        'modelId': MODEL_ID, 'runId': run_plan['runId'], 'evaluatedAt': utc_now(),
        'datasetSha256': manifest['sha256'], 'partitionPlanSha256': run_plan['partitionPlanSha256'],
        'runPlanSha256': sha256_file(args.output_dir / 'run-plan.json'),
        'freezeId': freeze['freezeId'], 'freezeSha256': marker['freezeSha256'],
        'checkpointSha256': freeze['files']['frozen-checkpoint.json'],
        'noMessageCheckpointSha256': freeze['files']['frozen-no-message-checkpoint.json'],
        'previousModelSha256': freeze['previousModelSha256'],
        'candidateOrder': identifiers, 'queries': 23, 'candidatesPerQuery': 23,
        'metrics': {label: result['metrics'] for label, result in results.items()}, 'results': results,
        'individualMemberResults': {
            label: [{'fold': member['fold'], 'selectedEpoch': member['selectedEpoch'],
                     **per_query_result(scores, identifiers)}
                    for member, scores in zip(artifact['members'], member_scores[label])]
            for label, artifact in (('gnn', model), ('noMessagePassing', no_model))
        },
        'memberScoreProvenance': 'Individual member results and equal-mean ensemble results use the same cached final score matrices. All five members remain included with fixed weight 0.2 regardless of these results.',
        'cvFoldSummary': cv_report['foldSummary'], 'selectedEpoch': freeze['selectedEpoch'],
        'noMessageSelectedEpoch': freeze['noMessageSelectedEpoch'],
        'fullDevelopmentRefit': False, 'ensemble': freeze['ensemble'], 'thresholds': FIXED_GATE,
        'priorExposure': run_plan['priorExposure'], 'limitations': LIMITATIONS,
        'baselineConclusion': 'All scores use the identical saved 23-query/23-candidate gallery. V1, v2 and this ensemble have different fitting protocols. This descriptive comparison cannot establish that full-development refitting caused any accuracy or weight-variance difference. No assumption that GNN beats name matching or the no-message ensemble.',
        'postEvaluationPolicy': 'No model, fold, seed, epoch, gate or aggregation selection from this report; new independent tasks are required for pristine unseen-data evaluation.',
    }
    report_hash = write_json(args.output_dir / 'final-evaluation-report.json', report)
    model['evaluation'] = {
        'status': 'BENCHMARK_PILOT', 'test': report['metrics'],
        'validation': {'gnn': cv_report['selection']['gnn']['pooledMetrics'],
                       'noMessagePassing': cv_report['selection']['noMessagePassing']['pooledMetrics'],
                       **cv_report['baselinePooledMetrics']},
        'crossValidation': {'folds': 5, 'gallerySize': 24, 'foldSummary': cv_report['foldSummary'],
                            'scope': cv_report['outOfFoldScope']},
        'finalHoldout': {'tasks': 23, 'gallerySize': 23, 'previouslyExposed': True,
                         'protocolChangedAfterExposure': True, 'evaluationReportSha256': report_hash},
        'financialDomainValidated': False,
        'scope': 'whole-program paired-task retrieval, not statement localization or formal equivalence',
    }
    model['provenance'].update({'freezeId': freeze['freezeId'], 'freezeSha256': marker['freezeSha256'],
                                'frozenCheckpointSha256': freeze['files']['frozen-checkpoint.json'],
                                'finalEvaluationReportSha256': report_hash})
    members_hash = sha256_bytes(canonical_bytes(model['members']))
    if members_hash != freeze['gnnMembersSha256']:
        raise ValueError('Deployment members changed after the checkpoint freeze.')
    deployed_hash = write_json(args.model_output, model, compact=True)
    deployment = {
        'modelId': MODEL_ID, 'runId': run_plan['runId'], 'modelSha256': deployed_hash,
        'frozenCheckpointSha256': freeze['files']['frozen-checkpoint.json'],
        'finalEvaluationReportSha256': report_hash, 'membersChangedAfterFreeze': False,
        'membersSha256': members_hash, 'fullDevelopmentRefit': False,
        'ensemble': freeze['ensemble'],
        'note': 'Only measured evaluation/provenance metadata are added; all five frozen rounded member weights, memberships, epochs, aggregation and gate remain unchanged.',
    }
    write_json(args.output_dir / 'deployment-manifest.json', deployment)
    return {'stage': 'FINAL_EVALUATED', 'runId': run_plan['runId'], 'metrics': report['metrics'],
            'modelSha256': deployed_hash, 'finalEvaluationReportSha256': report_hash,
            'modelOutput': str(args.model_output), 'fullDevelopmentRefit': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_mutually_exclusive_group(required=True)
    stages.add_argument('--prepare', action='store_true')
    stages.add_argument('--train', action='store_true')
    stages.add_argument('--evaluate-final', action='store_true')
    parser.add_argument('--dataset', type=Path, default=ROOT / 'evaluation/corpora/cobol-javatrans/COBOL-JavaTrans.jsonl')
    parser.add_argument('--partition-plan', type=Path, default=ROOT / 'evaluation/paired-code/cv-partition-plan.json')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--model-output', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--epochs', type=int, default=250)
    parser.add_argument('--seed', type=int, default=431)
    args = parser.parse_args()
    operation = prepare if args.prepare else train if args.train else evaluate_final
    print(json.dumps(operation(args), allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
