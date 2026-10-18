#!/usr/bin/env python3
"""Predeclared grouped 5-fold fitting followed by one frozen 23-task evaluation.

Run --prepare, --train and --evaluate-final in that order. Final-holdout graphs
are never learned-encoded/scored during fitting. Deterministic partitioning may
inspect all source graphs to keep related tasks together. The 23 tasks were evaluated by the older model:
this is a new fitting holdout, not a pristine or external unseen benchmark.
"""
from __future__ import annotations

import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml_engine.code_graph import FEATURE_NAMES, RELATIONS, build_graph
from ml_engine.paired_gnn import backward, batch_graphs, forward, initialise, paired_loss
from ml_engine.cv_partition import validate_partition_plan
from scripts.train_paired_gnn import name_tokens

MODEL_ID = 'paired-program-gnn-v2-cv'
DEFAULT_OUTPUT = ROOT / 'evaluation/paired-code/cv-v2'
DEFAULT_MODEL = ROOT / 'ml_engine/models/paired_program_gnn_v2_cv.json'
PREVIOUS_MODEL = ROOT / 'ml_engine/models/paired_program_gnn_v1.json'
FIXED_GATE = {
    'minimumSimilarity': 1.0,
    'minimumMargin': 2.0,
    'calibration': {
        'enabled': False,
        'reason': 'Benchmark-only retrieval evidence; financial-domain reliability remains unvalidated. Every ranking requires explicit human review.',
        'method': 'Fixed before CV and final evaluation; no holdout threshold selection.',
    },
}
LIMITATIONS = [
    '143 small HumanEval-derived source pairs, not banking migrations.',
    'Pair labels express upstream correspondence, not formal equivalence or defect locations.',
    'Heuristic operation graphs are not full compiler ASTs or control-flow graphs.',
    'Names are excluded from the model; the name-matching baseline can outperform it.',
    'Cosine similarities are not calibrated correctness probabilities.',
    'Final holdout is excluded from this fit and CV, but all 23 tasks were previously evaluated by v1; it is not pristine unseen or external data.',
    'Financial-domain generalization, repair, and defect prediction remain unvalidated.',
    'The selected-epoch out-of-fold results were used for epoch selection; they are exploratory selection evidence, not an unbiased nested-CV generalization estimate.',
    'CV galleries contain 24 candidates; final evaluation contains 23. Metrics from different gallery sizes or earlier 29-task reports are not directly comparable.',
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, value: dict, *, compact: bool = False) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value) if compact else (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(raw)
    temporary.replace(path)
    return sha256_bytes(raw)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def source_hashes() -> dict[str, str]:
    files = [Path(__file__), ROOT / 'ml_engine/code_graph.py', ROOT / 'ml_engine/paired_gnn.py', ROOT / 'scripts/train_paired_gnn.py',
             ROOT / 'ml_engine/cv_partition.py', ROOT / 'scripts/partition_paired_dataset.py']
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in files}


def load_dataset(path: Path) -> tuple[list[dict], dict]:
    raw = path.read_bytes()
    manifest = read_json(ROOT / 'evaluation/paired-code/dataset-manifest.json')
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    if sha256_bytes(raw) != manifest['sha256'] or len(rows) != 143:
        raise ValueError('Pinned dataset hash/143-task count mismatch.')
    if len({row['task_id'] for row in rows}) != 143:
        raise ValueError('Task IDs must be unique.')
    return rows, manifest


def validate_partition(plan: dict, rows: list[dict], dataset_sha256: str) -> None:
    """Fail closed on incorrect cardinalities, leakage, or group fragmentation."""
    if plan['datasetSha256'] != dataset_sha256:
        raise ValueError('Partition dataset hash mismatch.')
    ids = {row['task_id'] for row in rows}
    development, holdout = plan['developmentTaskIds'], plan['finalHoldoutTaskIds']
    if len(development) != 120 or len(set(development)) != 120 or len(holdout) != 23 or len(set(holdout)) != 23:
        raise ValueError('Partition must contain exactly 120 unique development and 23 unique final-holdout tasks.')
    if set(development) & set(holdout) or set(development) | set(holdout) != ids:
        raise ValueError('Development and holdout must be disjoint and cover all 143 tasks.')
    folds = plan['folds']
    if len(folds) != 5:
        raise ValueError('Exactly five folds are required.')
    observed = []
    for fold in folds:
        train, validation = fold['trainTaskIds'], fold['validationTaskIds']
        if len(train) != 96 or len(set(train)) != 96 or len(validation) != 24 or len(set(validation)) != 24:
            raise ValueError('Each fold must have 96 unique fitting and 24 unique validation tasks.')
        if set(train) & set(validation) or set(train) | set(validation) != set(development):
            raise ValueError('Each fold must partition development only, without holdout leakage.')
        observed.extend(validation)
    if len(observed) != 120 or set(observed) != set(development):
        raise ValueError('Each development task must be out-of-fold exactly once.')
    groups = plan.get('groups')
    if groups is None:
        groups = plan.get('graphPartitioning', {}).get('groups')
    if groups is not None:
        group_ids = [identifier for group in groups for identifier in group]
        if len(group_ids) != 143 or set(group_ids) != ids:
            raise ValueError('Graph partition components must partition all task IDs exactly once.')
        for group in groups:
            if set(group) & set(development) and set(group) & set(holdout):
                raise ValueError('Related task graph component crosses final holdout.')
            for fold in folds:
                if set(group) & set(fold['trainTaskIds']) and set(group) & set(fold['validationTaskIds']):
                    raise ValueError('Related task graph component crosses a CV fold.')
    # Deterministic inspection only: verifies graph components and score-independent
    # assignment from the source pairs; this does not use trained embeddings.
    validate_partition_plan(plan, rows)


def checkpoint_epochs(epochs: int) -> list[int]:
    if epochs < 1:
        raise ValueError('Epoch budget must be positive.')
    return sorted({1, epochs, *range(10, epochs + 1, 10)})


def ranks_from_scores(scores: np.ndarray) -> list[int]:
    n = len(scores)
    if scores.shape != (n, n) or n < 1 or not np.all(np.isfinite(scores)):
        raise ValueError('Retrieval scores must be a finite square paired-query gallery.')
    order = np.argsort(-scores, axis=1, kind='stable')
    return [int(np.flatnonzero(order[i] == i)[0]) + 1 for i in range(n)]


def rank_metrics(ranks: list[int], candidates_per_query: int | None = None) -> dict:
    values = np.asarray(ranks, dtype=float)
    if not len(values) or np.any(values < 1) or np.any(values != np.floor(values)):
        raise ValueError('Ranks must be nonempty positive integers.')
    result = {
        'queries': len(ranks),
        'top1': float(np.mean(values == 1)),
        'top3': float(np.mean(values <= 3)),
        'top5': float(np.mean(values <= 5)),
        'mrr': float(np.mean(1 / values)),
    }
    if candidates_per_query is not None:
        if np.any(values > candidates_per_query):
            raise ValueError('Rank exceeds gallery size.')
        result['candidatesPerQuery'] = candidates_per_query
    return result


def select_epoch(fold_histories: list[list[dict]]) -> dict:
    """Select pooled out-of-fold MRR, then weighted loss, then earliest epoch."""
    if not fold_histories or any(not history for history in fold_histories):
        raise ValueError('Nonempty histories are required for all folds.')
    schedules = [[record['epoch'] for record in history] for history in fold_histories]
    schedule = schedules[0]
    if schedule != sorted(set(schedule)) or any(epoch < 1 for epoch in schedule) or any(other != schedule for other in schedules):
        raise ValueError('Every fold must use the same unique increasing checkpoint epochs.')
    candidates = []
    for records in zip(*fold_histories):
        ranks = []
        sizes = []
        losses = []
        for record in records:
            n = len(record['ranks'])
            rank_metrics(record['ranks'], n)
            loss = float(record['validationLoss'])
            if not np.isfinite(loss):
                raise ValueError('Validation loss must be finite.')
            ranks.extend(record['ranks'])
            sizes.append(n)
            losses.append(loss)
        candidates.append({
            'epoch': records[0]['epoch'],
            'pooledMetrics': rank_metrics(ranks, sizes[0] if len(set(sizes)) == 1 else None),
            'weightedValidationLoss': float(np.average(losses, weights=sizes)),
            'candidatesPerQueryByFold': sizes,
        })
    best = max(candidates, key=lambda row: (row['pooledMetrics']['mrr'], -row['weightedValidationLoss'], -row['epoch']))
    return {'selectedEpoch': best['epoch'], **{key: value for key, value in best.items() if key != 'epoch'}, 'selectionHistory': candidates}


def adam_step(params: dict, first: dict, second: dict, gradients: dict, epoch: int) -> None:
    for name in params:
        gradient = np.clip(gradients[name] + 1e-4 * params[name], -5, 5)
        first[name] = .9 * first[name] + .1 * gradient
        second[name] = .999 * second[name] + .001 * gradient ** 2
        params[name] -= .004 * (first[name] / (1 - .9 ** epoch)) / (np.sqrt(second[name] / (1 - .999 ** epoch)) + 1e-8)


def _fresh_fit(graphs: tuple[list, list], train_indices: list[int], *, seed: int, epochs: int,
               message_passing: bool, validation_indices: list[int] | None = None) -> tuple[dict, list[dict]]:
    if not train_indices or len(set(train_indices)) != len(train_indices):
        raise ValueError('Unique nonempty fitting indices are required.')
    if validation_indices is not None and (not validation_indices or set(train_indices) & set(validation_indices)):
        raise ValueError('Fitting and validation indices must be nonempty and disjoint.')
    fitting = [batch_graphs([side[i] for i in train_indices], message_passing) for side in graphs]
    validation = None if validation_indices is None else [batch_graphs([side[i] for i in validation_indices], message_passing) for side in graphs]
    params = initialise(seed)
    first = {name: np.zeros_like(value) for name, value in params.items()}
    second = copy.deepcopy(first)
    history = []
    checkpoints = set(checkpoint_epochs(epochs))
    for epoch in range(1, epochs + 1):
        cobol, cache_cobol = forward(fitting[0], params, True)
        java, cache_java = forward(fitting[1], params, True)
        loss, dc, dj = paired_loss(cobol, java)
        gc, gj = backward(dc, cache_cobol, params), backward(dj, cache_java, params)
        adam_step(params, first, second, {name: gc[name] + gj[name] for name in params}, epoch)
        if validation is not None and epoch in checkpoints:
            cv, jv = [forward(batch, params) for batch in validation]
            ranks = ranks_from_scores(cv @ jv.T)
            history.append({'epoch': epoch, 'trainLoss': float(loss), 'validationLoss': float(paired_loss(cv, jv)[0]),
                            'ranks': ranks, **rank_metrics(ranks, len(ranks))})
    return params, history


def fit_fold(graphs: tuple[list, list], train_indices: list[int], validation_indices: list[int], *,
             seed: int, epochs: int, message_passing: bool) -> list[dict]:
    return _fresh_fit(graphs, train_indices, seed=seed, epochs=epochs, message_passing=message_passing,
                      validation_indices=validation_indices)[1]


def fit_full(graphs: tuple[list, list], indices: list[int], *, seed: int, epochs: int, message_passing: bool) -> dict:
    return _fresh_fit(graphs, indices, seed=seed, epochs=epochs, message_passing=message_passing)[0]


def graph_pairs(rows: list[dict]) -> tuple[list, list]:
    graphs = ([build_graph(row['COBOL_canonical_solution'], 'cobol') for row in rows],
              [build_graph(row['Java_canonical_solution'], 'java') for row in rows])
    if any(graph.stats['operations'] < 1 for side in graphs for graph in side):
        raise ValueError('Insufficient graph extraction: investigate rather than excluding tasks.')
    return graphs


def score_model(graphs: tuple[list, list], params: dict, message_passing: bool) -> np.ndarray:
    vectors = [forward(batch_graphs(side, message_passing), params) for side in graphs]
    return vectors[0] @ vectors[1].T


def baseline_scores(rows: list[dict], graphs: tuple[list, list]) -> dict[str, np.ndarray]:
    cobol_names = [name_tokens(row['COBOL_canonical_solution'], 'cobol') for row in rows]
    java_names = [name_tokens(row['Java_canonical_solution'], 'java') for row in rows]
    names = np.asarray([[len(a & b) / max(1, len(a | b)) for b in java_names] for a in cobol_names])
    vectors = [np.stack([graph.x.mean(axis=0) for graph in side]) for side in graphs]
    for vector in vectors:
        vector /= np.maximum(np.linalg.norm(vector, axis=1, keepdims=True), 1e-9)
    return {'nameMatching': names, 'semanticHistogram': vectors[0] @ vectors[1].T}


def per_query_result(scores: np.ndarray, identifiers: list[str]) -> dict:
    ranks = ranks_from_scores(scores)
    order = np.argsort(-scores, axis=1, kind='stable')
    return {
        'metrics': rank_metrics(ranks, len(identifiers)),
        'candidateOrder': identifiers,
        'queries': [{
            'taskId': identifier, 'correctCandidateTaskId': identifier,
            'rank': ranks[index], 'reciprocalRank': 1 / ranks[index],
            'correctCandidateSimilarity': float(scores[index, index]),
            'rankedCandidates': [{'taskId': identifiers[int(candidate)], 'similarity': float(scores[index, candidate])}
                                 for candidate in order[index]],
        } for index, identifier in enumerate(identifiers)],
    }


def prior_exposure(plan: dict) -> dict:
    old_splits = read_json(ROOT / 'evaluation/paired-code/task-splits.json')['splits']
    membership = {identifier: split for split, identifiers in old_splits.items() for identifier in identifiers}
    chosen = plan['finalHoldoutTaskIds']
    return {
        'previousModelId': 'paired-program-gnn-v1',
        'all143SourcesPreviouslyProcessed': True,
        'finalHoldoutTaskPriorMembership': {identifier: membership.get(identifier, 'UNKNOWN') for identifier in chosen},
        'priorMembershipCounts': {split: sum(membership.get(identifier) == split for identifier in chosen) for split in old_splits},
        'previouslyEvaluatedFinalHoldoutTasks': sum(membership.get(identifier) == 'test' for identifier in chosen),
        'limitation': 'The final 23 are held out from all new fitting/CV/gate choices, but were previously evaluated in v1. They cannot honestly be called pristine unforeseen data. New independently collected tasks are needed for that claim.',
        'priorSplitSha256': sha256_file(ROOT / 'evaluation/paired-code/task-splits.json'),
        'priorReportSha256': sha256_file(ROOT / 'evaluation/paired-code/training-report.json'),
    }


def verify_run_plan(args: argparse.Namespace) -> tuple[dict, dict, list[dict], dict]:
    run_plan = read_json(args.output_dir / 'run-plan.json')
    partition = read_json(args.partition_plan)
    rows, manifest = load_dataset(args.dataset)
    validate_partition(partition, rows, manifest['sha256'])
    if run_plan['partitionPlanSha256'] != sha256_file(args.partition_plan):
        raise ValueError('Partition plan changed after preparation.')
    if run_plan['sourceSha256'] != source_hashes():
        raise ValueError('Trainer/encoder code changed after preparation; prepare a new declared run before training.')
    if run_plan['datasetSha256'] != manifest['sha256']:
        raise ValueError('Prepared dataset mismatch.')
    if run_plan['configuration']['epochsBudget'] != args.epochs or run_plan['configuration']['seed'] != args.seed:
        raise ValueError('Epoch budget/seed differs from frozen run plan.')
    return run_plan, partition, rows, manifest


def prepare(args: argparse.Namespace) -> dict:
    if (args.output_dir / 'run-plan.json').exists():
        raise ValueError('A run plan already exists. Preserve its audit trail; use a new output directory for a separately declared experiment.')
    rows, manifest = load_dataset(args.dataset)
    partition = read_json(args.partition_plan)
    validate_partition(partition, rows, manifest['sha256'])
    if partition['seed'] != args.seed:
        raise ValueError('Run seed must match partition seed.')
    plan = {
        'schemaVersion': 1, 'modelId': MODEL_ID, 'createdAt': utc_now(),
        'datasetSha256': manifest['sha256'], 'partitionPlanSha256': sha256_file(args.partition_plan),
        'sourceSha256': source_hashes(), 'numpyVersion': np.__version__,
        'previousModel': {'id': read_json(PREVIOUS_MODEL)['id'], 'sha256': sha256_file(PREVIOUS_MODEL),
                          'path': str(PREVIOUS_MODEL.relative_to(ROOT)),
                          'purpose': 'Frozen descriptive baseline on the exact same final 23-task gallery; never used for selection.'},
        'configuration': {
            'seed': args.seed, 'epochsBudget': args.epochs, 'checkpointEpochs': checkpoint_epochs(args.epochs),
            'foldCount': 5, 'developmentTasks': 120, 'finalHoldoutTasks': 23,
            'foldTrainingTasks': 96, 'foldValidationTasks': 24,
            'initialization': 'Fresh parameters and fresh Adam state per fold, ablation, and final full-development fit; same declared seed.',
            'architecture': 'Unchanged two-layer relation-aware GNN; hidden/output 24; shared COBOL/Java encoder.',
            'optimizer': {'name': 'Adam', 'learningRate': .004, 'beta1': .9, 'beta2': .999, 'epsilon': 1e-8, 'weightDecay': .0001, 'gradientClip': 5},
            'objective': 'Symmetric paired-source InfoNCE, temperature 0.12; in-batch negatives only from current fitting fold.',
            'selection': 'Pooled 120 out-of-fold reciprocal ranks (MRR), then query-weighted validation loss, then earliest checkpoint epoch. No test-based tuning.',
            'ablation': 'No-message model has identical capacity, initialization seed, optimizer, epoch budget, folds, and its own identical CV epoch-selection rule.',
            'thresholds': FIXED_GATE,
            'ties': 'Stable candidate order saved in the partition plan; equal scores retain that order.',
            'finalProtocol': 'Freeze both full-development checkpoints, selected epochs, gate, and CV report before any learned encoding/scoring of the 23 final-holdout tasks. Deterministic graph partitioning may inspect all tasks before fitting. One final evaluation per frozen run.',
            'prohibited': ['No final-holdout graphs/embeddings/loss/negative-gallery in CV or fitting.', 'No augmentation, architecture change, threshold search or test-driven hyperparameter search.'],
        },
        'priorExposure': prior_exposure(partition),
        'limitations': LIMITATIONS,
    }
    plan['runId'] = 'paired-cv-v2-' + sha256_bytes(canonical_bytes(plan))[:16]
    digest = write_json(args.output_dir / 'run-plan.json', plan)
    return {'stage': 'PREPARED', 'runId': plan['runId'], 'runPlanSha256': digest,
            'counts': {'development': 120, 'finalHoldout': 23, 'folds': 5}}


def summarise_folds(folds: list[dict], selected_epoch: int) -> dict:
    selected = [next(row for row in fold['history'] if row['epoch'] == selected_epoch) for fold in folds]
    names = ('top1', 'top3', 'top5', 'mrr')
    return {
        'selectedEpoch': selected_epoch,
        'mean': {name: float(np.mean([row[name] for row in selected])) for name in names},
        'standardDeviation': {name: float(np.std([row[name] for row in selected], ddof=1)) for name in names},
        'standardDeviationDefinition': 'Sample standard deviation across five held-out folds; not a confidence interval.',
    }


def make_model(params: dict, run_plan: dict, partition: dict, manifest: dict, selection: dict, no_selection: dict) -> dict:
    return {
        'id': MODEL_ID,
        'architecture': '2-layer relation-aware GNN; tanh; mean pools both layers; learned readout; cosine retrieval',
        'featureNames': list(FEATURE_NAMES), 'relations': list(RELATIONS),
        'weights': {name: value.round(12).tolist() for name, value in params.items()},
        'training': {
            'dataset': 'COBOL-JavaTrans (143 original source pairs; 120 development / 23 final fitting holdout)',
            'datasetSha256': manifest['sha256'], 'sourceCommit': manifest['commit'],
            'seed': run_plan['configuration']['seed'], 'epochsBudget': run_plan['configuration']['epochsBudget'],
            'selectedEpoch': selection['selectedEpoch'], 'noMessageSelectedEpoch': no_selection['selectedEpoch'],
            'objective': 'symmetric paired-source InfoNCE; temperature0.12; Adam0.004; weight decay0.0001',
            'splitCounts': {'development': 120, 'finalHoldout': 23},
            'crossValidation': {'folds': 5, 'trainPerFold': 96, 'validationPerFold': 24,
                                'selectedPooledOutOfFoldMetrics': selection['pooledMetrics']},
            'selection': run_plan['configuration']['selection'],
            'fullDevelopmentRefit': True,
            'featureLeakageControls': ['identifier spelling excluded', 'comments excluded', 'program/method/task names excluded', 'whole related-task graph components kept together before fitting'],
        },
        'thresholds': copy.deepcopy(FIXED_GATE),
        'evaluation': {'status': 'FROZEN_AWAITING_FINAL_EVALUATION', 'test': {'status': 'NOT_EVALUATED'},
                       'validation': {'gnn': selection['pooledMetrics']}, 'financialDomainValidated': False,
                       'scope': 'whole-program paired-task retrieval, not statement localization or formal equivalence'},
        'limitations': LIMITATIONS,
        'provenance': {'dataset': manifest, 'trainedOn': datetime.now(timezone.utc).date().isoformat(),
                       'runId': run_plan['runId'], 'partitionPlanSha256': run_plan['partitionPlanSha256'],
                       'generatedBy': 'AI-assisted implementation; actual CPU fitting on pinned paired source',
                       'finalHoldoutPriorExposure': run_plan['priorExposure']},
    }


def train(args: argparse.Namespace) -> dict:
    if (args.output_dir / 'model-freeze.json').exists() or (args.output_dir / 'final-evaluation-started.json').exists():
        raise ValueError('This declared run is already frozen/evaluated; refuse retraining over its audit trail.')
    started = time.monotonic()
    run_plan, partition, rows, manifest = verify_run_plan(args)
    with (args.output_dir / 'training-started.json').open('x') as handle:
        json.dump({'runId': run_plan['runId'], 'startedAt': utc_now(),
                   'note': 'Exclusive training marker; preserve this run audit if fitting fails.'}, handle, indent=2)
        handle.write('\n')
    by_id = {row['task_id']: row for row in rows}
    development_ids = partition['developmentTaskIds']
    # Only these 120 source pairs are transformed into graphs during CV and refit.
    development_rows = [by_id[identifier] for identifier in development_ids]
    graphs = graph_pairs(development_rows)
    index = {identifier: i for i, identifier in enumerate(development_ids)}
    folds_by_model = {'gnn': [], 'noMessagePassing': []}
    baseline_folds = []
    for fold in partition['folds']:
        train_indices = [index[identifier] for identifier in fold['trainTaskIds']]
        validation_indices = [index[identifier] for identifier in fold['validationTaskIds']]
        for label, use_messages in (('gnn', True), ('noMessagePassing', False)):
            history = fit_fold(graphs, train_indices, validation_indices, seed=args.seed,
                               epochs=args.epochs, message_passing=use_messages)
            folds_by_model[label].append({'fold': fold['fold'], 'trainTaskIds': fold['trainTaskIds'],
                                         'candidateOrder': fold['validationTaskIds'], 'history': history})
            print(json.dumps({'stage': 'CV_FOLD_COMPLETE', 'model': label, 'fold': fold['fold'],
                              'epochsBudget': args.epochs, 'validationTasks': len(validation_indices)}), flush=True)
        selected_graphs = tuple([side[i] for i in validation_indices] for side in graphs)
        selected_rows = [development_rows[i] for i in validation_indices]
        baseline_folds.append({'fold': fold['fold'], **{
            label: per_query_result(scores, fold['validationTaskIds'])
            for label, scores in baseline_scores(selected_rows, selected_graphs).items()}})
    selections = {label: select_epoch([fold['history'] for fold in folds]) for label, folds in folds_by_model.items()}
    for label, folds in folds_by_model.items():
        selected_epoch = selections[label]['selectedEpoch']
        for fold in folds:
            selected = next(record for record in fold['history'] if record['epoch'] == selected_epoch)
            fold['selectedCheckpointPerQuery'] = [
                {'taskId': identifier, 'correctCandidateTaskId': identifier, 'rank': rank, 'reciprocalRank': 1 / rank}
                for identifier, rank in zip(fold['candidateOrder'], selected['ranks'])]
    report = {
        'modelId': MODEL_ID, 'runId': run_plan['runId'], 'createdAt': utc_now(),
        'runPlanSha256': sha256_file(args.output_dir / 'run-plan.json'),
        'partitionPlanSha256': run_plan['partitionPlanSha256'],
        'datasetSha256': manifest['sha256'],
        'developmentTasks': 120, 'finalHoldoutTasksNeverLearnedEncodedOrScoredAtThisStage': 23,
        'partitionInspectionNote': 'Deterministic graph partitioning inspected all tasks before training to prevent related-task leakage. No final-holdout graph enters learned fitting, CV, negatives or epoch selection.',
        'selection': selections, 'folds': folds_by_model,
        'foldSummary': {label: summarise_folds(folds, selections[label]['selectedEpoch']) for label, folds in folds_by_model.items()},
        'baselineFolds': baseline_folds,
        'baselinePooledMetrics': {label: rank_metrics([query['rank'] for fold in baseline_folds for query in fold[label]['queries']], 24)
                                  for label in ('nameMatching', 'semanticHistogram')},
        'thresholds': FIXED_GATE, 'priorExposure': run_plan['priorExposure'], 'limitations': LIMITATIONS,
    }
    all_indices = list(range(120))
    params = fit_full(graphs, all_indices, seed=args.seed, epochs=selections['gnn']['selectedEpoch'], message_passing=True)
    no_params = fit_full(graphs, all_indices, seed=args.seed, epochs=selections['noMessagePassing']['selectedEpoch'], message_passing=False)
    model = make_model(params, run_plan, partition, manifest, selections['gnn'], selections['noMessagePassing'])
    no_model = make_model(no_params, run_plan, partition, manifest, selections['noMessagePassing'], selections['noMessagePassing'])
    no_model['id'] = 'paired-program-no-message-v2-cv'
    no_model['architecture'] += '; relation edges removed for ablation'
    report['durationSeconds'] = round(time.monotonic() - started, 3)
    report_hash = write_json(args.output_dir / 'cv-training-report.json', report)
    model_hash = write_json(args.output_dir / 'frozen-checkpoint.json', model, compact=True)
    no_hash = write_json(args.output_dir / 'frozen-no-message-checkpoint.json', no_model, compact=True)
    freeze = {
        'schemaVersion': 1, 'runId': run_plan['runId'], 'frozenAt': utc_now(),
        'runPlanSha256': sha256_file(args.output_dir / 'run-plan.json'),
        'partitionPlanSha256': sha256_file(args.partition_plan),
        'sourceSha256': source_hashes(), 'datasetSha256': manifest['sha256'],
        'gnnWeightsSha256': sha256_bytes(canonical_bytes(model['weights'])),
        'noMessageWeightsSha256': sha256_bytes(canonical_bytes(no_model['weights'])),
        'files': {'frozen-checkpoint.json': model_hash, 'frozen-no-message-checkpoint.json': no_hash,
                  'cv-training-report.json': report_hash},
        'selectedEpoch': selections['gnn']['selectedEpoch'],
        'noMessageSelectedEpoch': selections['noMessagePassing']['selectedEpoch'],
        'thresholds': FIXED_GATE,
        'previousModelSha256': run_plan['previousModel']['sha256'],
        'finalHoldoutLearnedEncodingOrScoringPerformed': False,
        'finalEvaluationRule': 'One evaluation of the frozen checkpoints and pinned previous-model baseline against the declared 23-task gallery; never retrain or tune from its results.',
    }
    freeze['freezeId'] = 'paired-cv-freeze-' + sha256_bytes(canonical_bytes(freeze))[:16]
    freeze_hash = write_json(args.output_dir / 'model-freeze.json', freeze)
    return {'stage': 'FROZEN', 'runId': run_plan['runId'], 'freezeId': freeze['freezeId'],
            'freezeSha256': freeze_hash, 'selectedEpochs': {label: value['selectedEpoch'] for label, value in selections.items()},
            'cvPooledMetrics': {label: value['pooledMetrics'] for label, value in selections.items()},
            'durationSeconds': report['durationSeconds']}


def evaluate_final(args: argparse.Namespace) -> dict:
    if (args.output_dir / 'final-evaluation-report.json').exists():
        raise ValueError('Final evaluation already completed; inspect its saved report instead of rerunning or selecting on holdout.')
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
    if model['thresholds'] != FIXED_GATE or freeze['thresholds'] != FIXED_GATE:
        raise ValueError('Fixed human-review gate changed after predeclaration.')
    if sha256_file(PREVIOUS_MODEL) != run_plan['previousModel']['sha256'] or freeze['previousModelSha256'] != run_plan['previousModel']['sha256']:
        raise ValueError('Pinned previous-model baseline changed after preparation/freeze.')
    previous_model = read_json(PREVIOUS_MODEL)
    marker = {'runId': run_plan['runId'], 'freezeId': freeze['freezeId'], 'freezeSha256': sha256_file(freeze_path),
              'startedAt': utc_now(), 'warning': 'One-shot marker. Preserve even if evaluation fails; do not silently repeat or tune on this holdout.'}
    with (args.output_dir / 'final-evaluation-started.json').open('x') as handle:
        json.dump(marker, handle, indent=2)
        handle.write('\n')
    # First learned final-holdout encoding/scoring in this declared run. The
    # earlier deterministic partitioning inspection is disclosed in the plan.
    by_id = {row['task_id']: row for row in rows}
    identifiers = partition['finalHoldoutTaskIds']
    final_rows = [by_id[identifier] for identifier in identifiers]
    graphs = graph_pairs(final_rows)
    params = {name: np.asarray(value, dtype=float) for name, value in model['weights'].items()}
    no_params = {name: np.asarray(value, dtype=float) for name, value in no_model['weights'].items()}
    previous_params = {name: np.asarray(value, dtype=float) for name, value in previous_model['weights'].items()}
    scores = {'gnn': score_model(graphs, params, True), 'noMessagePassing': score_model(graphs, no_params, False),
              'previousV1Gnn': score_model(graphs, previous_params, True),
              **baseline_scores(final_rows, graphs)}
    results = {label: per_query_result(values, identifiers) for label, values in scores.items()}
    cv_report = read_json(args.output_dir / 'cv-training-report.json')
    report = {
        'schemaVersion': 1, 'modelId': MODEL_ID, 'runId': run_plan['runId'], 'freezeId': freeze['freezeId'],
        'evaluatedAt': utc_now(), 'datasetSha256': manifest['sha256'],
        'runPlanSha256': freeze['runPlanSha256'], 'partitionPlanSha256': freeze['partitionPlanSha256'],
        'freezeSha256': marker['freezeSha256'], 'checkpointSha256': freeze['files']['frozen-checkpoint.json'],
        'noMessageCheckpointSha256': freeze['files']['frozen-no-message-checkpoint.json'],
        'previousModelSha256': run_plan['previousModel']['sha256'],
        'candidateOrder': identifiers, 'queries': 23, 'candidatesPerQuery': 23,
        'metrics': {label: result['metrics'] for label, result in results.items()}, 'results': results,
        'cvFoldSummary': cv_report['foldSummary'], 'selectedEpoch': freeze['selectedEpoch'],
        'noMessageSelectedEpoch': freeze['noMessageSelectedEpoch'], 'thresholds': FIXED_GATE,
        'priorExposure': run_plan['priorExposure'], 'limitations': LIMITATIONS,
        'baselineConclusion': 'Compare all models on this identical saved 23-candidate gallery. The old v1 model used 85 fitting/29 validation tasks; v2 uses 120 development tasks with 5-fold selection, so old-vs-new is descriptive and does not isolate one causal change. No assumption that GNN beats name matching or the no-message ablation.',
        'postEvaluationPolicy': 'No tuning from this report; additional model changes require new development work and genuinely new external evaluation data.',
    }
    report_hash = write_json(args.output_dir / 'final-evaluation-report.json', report)
    model['evaluation'] = {
        'status': 'BENCHMARK_PILOT',
        'test': report['metrics'],
        'validation': {'gnn': cv_report['selection']['gnn']['pooledMetrics'],
                       'noMessagePassing': cv_report['selection']['noMessagePassing']['pooledMetrics'],
                       **cv_report['baselinePooledMetrics']},
        'crossValidation': {'folds': 5, 'gallerySize': 24, 'foldSummary': cv_report['foldSummary']},
        'finalHoldout': {'tasks': 23, 'gallerySize': 23, 'previouslyExposed': True, 'evaluationReportSha256': report_hash},
        'financialDomainValidated': False,
        'scope': 'whole-program paired-task retrieval, not statement localization or formal equivalence',
    }
    model['provenance'].update({'freezeId': freeze['freezeId'], 'freezeSha256': marker['freezeSha256'],
                                'frozenCheckpointSha256': freeze['files']['frozen-checkpoint.json'],
                                'finalEvaluationReportSha256': report_hash})
    weights_hash = sha256_bytes(canonical_bytes(model['weights']))
    if weights_hash != freeze['gnnWeightsSha256']:
        raise ValueError('Deployment weights changed after final checkpoint freeze.')
    deployed_hash = write_json(args.model_output, model, compact=True)
    deployment = {'modelId': MODEL_ID, 'runId': run_plan['runId'], 'modelSha256': deployed_hash,
                  'frozenCheckpointSha256': freeze['files']['frozen-checkpoint.json'],
                  'finalEvaluationReportSha256': report_hash, 'weightsChangedAfterFreeze': False,
                  'weightsSha256': weights_hash,
                  'note': 'Deployment artifact adds measured evaluation/provenance metadata; exact frozen rounded weights and gate are preserved.'}
    write_json(args.output_dir / 'deployment-manifest.json', deployment)
    return {'stage': 'FINAL_EVALUATED', 'runId': run_plan['runId'], 'metrics': report['metrics'],
            'modelSha256': deployed_hash, 'finalEvaluationReportSha256': report_hash,
            'modelOutput': str(args.model_output)}


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
