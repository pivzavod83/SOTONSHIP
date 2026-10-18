#!/usr/bin/env python3
"""Predeclared four-candidate comparison; selection on 120 development pairs only.

The baseline and four improvements retain five 96-pair models. Select by pooled
out-of-fold Top-1, then MRR, then fixed candidate order. Freeze every candidate
and the winner before the once-only reused 23-pair evaluation. Never fit120.
"""
from __future__ import annotations
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml_engine.code_graph import FEATURE_NAMES, RELATIONS
from ml_engine.paired_gnn import batch_graphs, initialise, forward, backward, paired_loss, load_model
from ml_engine.candidate_gnn import initialise_candidate, forward_candidate, backward_candidate, augment_batch
from ml_engine.structural_cca import graph_features, fit_cca, encode_cca
from scripts.train_paired_gnn_cv import (FIXED_GATE, adam_step, baseline_scores, canonical_bytes,
    checkpoint_epochs, graph_pairs, load_dataset, per_query_result, rank_metrics, ranks_from_scores,
    read_json, sha256_bytes, sha256_file, utc_now, validate_partition, write_json)

DEFAULT_OUTPUT = ROOT / 'evaluation/paired-code/cv-v4-candidates'
DEFAULT_MODEL = ROOT / 'ml_engine/models/paired_program_v4_selected.json'
# Fixed simplicity tie-break, declared before any fitting or new CV scoring.
ORDER = ('baseline', 'structural_cca', 'graph_regularized', 'language_heads', 'count_readout')
PAPERS = {
    'count_readout': {'title': 'How Powerful are Graph Neural Networks?', 'authors': 'Xu et al.',
        'venue': 'ICLR 2019', 'url': 'https://arxiv.org/abs/1810.00826',
        'adaptation': 'Mean/max/scaled-sum layer readouts plus explicit log node count. Motivated by multiset/count expressiveness; not a GIN reproduction or expressivity proof.'},
    'language_heads': {'title': 'Deep Canonical Correlation Analysis', 'authors': 'Andrew et al.',
        'venue': 'ICML 2013', 'url': 'https://proceedings.mlr.press/v28/andrew13.html',
        'adaptation': 'Shared GNN backbone with separate paired-view COBOL/Java projections, trained with InfoNCE. Paired-view motivation, not the DCCA objective.'},
    'structural_cca': {'title': 'Weisfeiler-Lehman Graph Kernels', 'authors': 'Shervashidze et al.',
        'venue': 'JMLR 2011', 'url': 'https://www.jmlr.org/papers/v12/shervashidze11a.html',
        'additionalPaper': 'https://proceedings.mlr.press/v28/andrew13.html',
        'adaptation': 'Fixed hashed relation-aware WL counts and semantic statistics; fold-local standardization and regularized linear CCA (ridge0.1,24outputs), not DCCA.'},
    'graph_regularized': {'title': 'Graph Contrastive Learning with Augmentations', 'authors': 'You et al.',
        'venue': 'NeurIPS 2020', 'url': 'https://proceedings.neurips.cc/paper/2020/hash/3fe230348e9a12c13120749e3f9fa4cd-Abstract.html',
        'adaptation': '10% auxiliary sequence-edge dropout during fitting, preserving paired directions and all data/control edges and numeric features. GraphCL-inspired regularization, not a full GraphCL reproduction.'},
}
LIMITATIONS = [
    '143 small HumanEval-derived paired tasks, not production banking migrations or defect labels.',
    'All23 final tasks were evaluated in v1/v2/v3. This new protocol was requested after earlier results were visible; final results are descriptive on a reused benchmark, not pristine unseen-data evidence.',
    'Every learned transformation and preprocessing statistic uses only its96 fitting pairs. No120-pair full-development fit or refit.',
    'CV evaluates each query by its one designated held-out member, not by the other four members that trained on it; CV is a selection statistic, not nested unbiased ensemble validation.',
    'Names, comments, task IDs and method/program names are excluded from learned features. Structural graphs are heuristic, not compiler semantics.',
    'Graph dropout is regularization on views of original fitting pairs, not additional authentic source pairs or a behavior-preserving code transformation.',
    'Paper results motivate these adaptations; they do not guarantee gains on COBOL-JavaTrans.',
    'Matching cosine is not a correctness probability or equivalence proof. Every result requires review; Z3 is independent.',
    'All final candidates are reported, but deployment follows the frozen CV winner even if another final score is higher. No final-driven tuning, member choice or model switch.',
]


def source_hashes() -> dict:
    files = [Path(__file__), ROOT/'scripts/train_paired_gnn_cv.py', ROOT/'scripts/train_paired_gnn.py',
        ROOT/'scripts/partition_paired_dataset.py', *[ROOT/'ml_engine'/name for name in (
            'code_graph.py', 'cv_partition.py', 'paired_gnn.py', 'candidate_gnn.py',
            'structural_cca.py', 'candidate_retrieval.py', 'matching.py')]]
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in files}


def verify_plan(args):
    plan = read_json(args.output_dir/'run-plan.json')
    partition = read_json(args.partition_plan)
    rows, manifest = load_dataset(args.dataset)
    validate_partition(partition, rows, manifest['sha256'])
    if (plan['partitionPlanSha256'] != sha256_file(args.partition_plan)
            or plan['sourceSha256'] != source_hashes() or plan['datasetSha256'] != manifest['sha256']
            or plan['configuration']['epochsBudget'] != args.epochs or plan['configuration']['seed'] != args.seed):
        raise ValueError('Prepared partition, source, data or configuration changed.')
    for name, digest in plan['sourceSha256'].items():
        if sha256_file(args.output_dir/'source-snapshot'/name) != digest:
            raise ValueError('Prepared source snapshot changed: '+name)
    return plan, partition, rows, manifest


def prepare(args):
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError('Use a new empty experiment directory; never overwrite completed evidence.')
    rows, manifest = load_dataset(args.dataset)
    partition = read_json(args.partition_plan)
    validate_partition(partition, rows, manifest['sha256'])
    if args.seed != partition['seed']:
        raise ValueError('Seed must match frozen partition.')
    hashes = source_hashes()
    for name, digest in hashes.items():
        raw = (ROOT/name).read_bytes()
        if sha256_bytes(raw) != digest:
            raise ValueError('Source changed during preparation.')
        path = args.output_dir/'source-snapshot'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle:
            handle.write(raw)
    plan = {
        'schemaVersion': 1, 'createdAt': utc_now(), 'sourceSha256': hashes,
        'datasetSha256': manifest['sha256'], 'partitionPlanSha256': sha256_file(args.partition_plan),
        'numpyVersion': np.__version__, 'papers': PAPERS,
        'configuration': {'candidates': list(ORDER), 'newImprovements': 4,
            'seed': args.seed, 'epochsBudget': args.epochs, 'checkpointEpochs': checkpoint_epochs(args.epochs),
            'folds': 5, 'trainingPerFold': 96, 'validationPerFold': 24,
            'developmentPairs': 120, 'finalEvaluationPairs': 23, 'fullDevelopmentRefit': False,
            'selection': 'Checkpoint: pooled120 OOF Top1, then MRR, then lower validation loss, then earliest epoch. Candidate: pooled OOF Top1, then MRR, then fixed declared simplicity order.',
            'candidateTieOrder': list(ORDER), 'ensemble': {'aggregation': 'MEAN_COSINE', 'members': 5},
            'neuralTraining': {'objective': 'symmetric paired InfoNCE', 'temperature': .12, 'optimizer': 'Adam',
                'learningRate': .004, 'weightDecay': .0001, 'hidden': 24, 'output': 24,
                'initialization': 'fresh parameters and Adam state for every96-pair fold'},
            'structuralCca': {'regularization': .1, 'output': 24, 'rounds': [0, 1, 2], 'hashBins': 512,
                'preprocessing': 'means/scales and CCA fitted exclusively on each96-pair fitting fold'},
            'augmentation': {'sequenceEdgeDropout': .1, 'evaluation': 'unmodified graphs', 'featureMasking': False},
            'thresholds': FIXED_GATE,
            'finalProtocol': 'Freeze all5candidate ensembles and CVwinner before final learned encoding; evaluate all on same23once; deploy CVwinner regardless final ranking.',
            'partitionPolicyOverride': 'Reuse v2/v3 graph components and exact120/23/foldassignments. Supersede historical full-development refit policy: neverfit120.',
        },
        'priorExposure': {'previouslyEvaluated': True, 'protocolChangedAfterExposure': True,
            'previousV3ReportSha256': sha256_file(ROOT/'evaluation/paired-code/cv-v3-fold-ensemble/final-evaluation-report.json')},
        'limitations': LIMITATIONS,
    }
    plan['runId'] = 'paired-v4-candidates-'+sha256_bytes(canonical_bytes(plan))[:16]
    digest = write_json(args.output_dir/'run-plan.json', plan)
    return {'stage': 'PREPARED', 'runId': plan['runId'], 'runPlanSha256': digest}


def select_checkpoint(histories):
    schedule = [[item['epoch'] for item in history] for history in histories]
    if len(histories) != 5 or not schedule[0] or any(other != schedule[0] for other in schedule):
        raise ValueError('Five consistent fold checkpoint histories required.')
    choices = []
    for records in zip(*histories):
        ranks = [rank for record in records for rank in record['ranks']]
        choices.append({'selectedEpoch': records[0]['epoch'], 'pooledMetrics': rank_metrics(ranks, 24),
                        'validationLoss': float(np.mean([r['validationLoss'] for r in records]))})
    best = max(choices, key=lambda item: (item['pooledMetrics']['top1'], item['pooledMetrics']['mrr'],
                                       -item['validationLoss'], -item['selectedEpoch']))
    return {**best, 'history': choices}


def select_winner(selections):
    if set(selections) != set(ORDER):
        raise ValueError('Every declared candidate must finish before model selection.')
    return max(ORDER, key=lambda name: (selections[name]['pooledMetrics']['top1'],
               selections[name]['pooledMetrics']['mrr'], -ORDER.index(name)))


def fit_neural(graphs, fitting, validation, candidate, seed, epochs):
    if len(fitting) != 96 or len(validation) != 24 or set(fitting) & set(validation):
        raise ValueError('Each neural fit requires disjoint96/24development indices.')
    train_batches = [batch_graphs([side[i] for i in fitting]) for side in graphs]
    val_batches = [batch_graphs([side[i] for i in validation]) for side in graphs]
    params = initialise(seed) if candidate == 'baseline' else initialise_candidate(candidate, seed)
    first = {k: np.zeros_like(v) for k, v in params.items()}
    second = {k: np.zeros_like(v) for k, v in params.items()}
    rng = np.random.default_rng(seed + 1729)
    history, states = [], {}
    def run(batch, language, cache=False):
        return forward(batch, params, cache) if candidate == 'baseline' else forward_candidate(batch, params, candidate, language, cache)
    for epoch in range(1, epochs+1):
        batches = [augment_batch(batch, rng) for batch in train_batches] if candidate == 'graph_regularized' else train_batches
        c, cc = run(batches[0], 'cobol', True)
        j, jc = run(batches[1], 'java', True)
        loss, dc, dj = paired_loss(c, j)
        if candidate == 'baseline':
            gc, gj = backward(dc, cc, params), backward(dj, jc, params)
        else:
            gc = backward_candidate(dc, cc, params, candidate, 'cobol')
            gj = backward_candidate(dj, jc, params, candidate, 'java')
        adam_step(params, first, second, {k: gc[k]+gj[k] for k in params}, epoch)
        if epoch in checkpoint_epochs(epochs):
            cv, jv = run(val_batches[0], 'cobol'), run(val_batches[1], 'java')
            ranks = ranks_from_scores(cv@jv.T)
            history.append({'epoch': epoch, 'trainLoss': float(loss), 'validationLoss': float(paired_loss(cv, jv)[0]),
                            'ranks': ranks, **rank_metrics(ranks, 24)})
            states[epoch] = {'weights': {k: v.copy() for k, v in params.items()}}
    return history, states


def rounded_state(state):
    if 'weights' in state:
        return {'weights': {k: v.round(12).tolist() for k, v in state['weights'].items()}}
    # CCA returns JSON-ready state; preserve its full floating-point precision.
    return state


def make_model(candidate, members, selection, plan, manifest):
    return {
        'id': 'paired-program-v4-'+candidate, 'kind': 'SELECTED_FOLD_ENSEMBLE', 'candidateId': candidate,
        'featureNames': list(FEATURE_NAMES), 'relations': list(RELATIONS),
        'ensemble': {'aggregation': 'MEAN_COSINE', 'members': 5}, 'members': members,
        'training': {'dataset': 'COBOL-JavaTrans (143 actual pairs;120development/23reserved)',
            'datasetSha256': manifest['sha256'], 'seed': plan['configuration']['seed'],
            'selectedEpoch': selection['selectedEpoch'], 'fullDevelopmentRefit': False,
            'splitCounts': {'development': 120, 'finalHoldout': 23},
            'crossValidation': {'folds': 5, 'trainPerFold': 96, 'validationPerFold': 24,
                'selectedPooledOutOfFoldMetrics': selection['pooledMetrics']},
            'selection': plan['configuration']['selection'], 'fittingPairsPerMember': 96},
        'thresholds': FIXED_GATE,
        'evaluation': {'status': 'FROZEN_AWAITING_FINAL_EVALUATION', 'financialDomainValidated': False,
            'validation': selection['pooledMetrics']},
        'limitations': LIMITATIONS,
        'provenance': {'runId': plan['runId'], 'partitionPlanSha256': plan['partitionPlanSha256'],
            'papers': PAPERS.get(candidate), 'generatedBy': 'AI-assisted implementation and actual CPU fitting on original paired sources'},
    }


def train(args):
    plan, partition, rows, manifest = verify_plan(args)
    if (args.output_dir/'model-freeze.json').exists():
        raise ValueError('Run already frozen; do not refit or replace evidence.')
    with (args.output_dir/'training-started.json').open('x') as handle:
        json.dump({'runId': plan['runId'], 'startedAt': utc_now(), 'fullDevelopmentRefit': False}, handle)
    started = time.monotonic()
    by_id = {row['task_id']: row for row in rows}
    identifiers = partition['developmentTaskIds']
    index = {value: i for i, value in enumerate(identifiers)}
    # No final task source is passed to any learned encoder/features at this stage.
    graphs = graph_pairs([by_id[value] for value in identifiers])
    features = tuple(np.stack([graph_features(graph) for graph in side]) for side in graphs)
    fold_reports = {name: [] for name in ORDER}
    checkpoints = {name: [] for name in ORDER}
    for fold in partition['folds']:
        fit = [index[value] for value in fold['trainTaskIds']]
        val = [index[value] for value in fold['validationTaskIds']]
        for name in ORDER:
            if name == 'structural_cca':
                state = fit_cca(features[0][fit], features[1][fit], regularization=.1, output=24)
                c, j = [encode_cca(side[val], state, language) for side, language in zip(features, ('cobol', 'java'))]
                ranks = ranks_from_scores(c@j.T)
                history = [{'epoch': 1, 'validationLoss': float(paired_loss(c, j)[0]), 'ranks': ranks, **rank_metrics(ranks, 24)}]
                states = {1: state}
            else:
                history, states = fit_neural(graphs, fit, val, name, args.seed, args.epochs)
            fold_reports[name].append({'fold': fold['fold'], 'trainTaskIds': fold['trainTaskIds'],
                'candidateOrder': fold['validationTaskIds'], 'history': history})
            checkpoints[name].append(states)
            print(json.dumps({'stage': 'CV_FOLD_COMPLETE', 'candidate': name, 'fold': fold['fold'],
                'fittingPairs': 96, 'validationPairs': 24}), flush=True)
    selections = {name: select_checkpoint([fold['history'] for fold in folds]) for name, folds in fold_reports.items()}
    winner = select_winner(selections)
    files, member_hashes = {}, {}
    for name in ORDER:
        epoch = selections[name]['selectedEpoch']
        members = [{'fold': fold['fold'], 'trainingTaskIds': fold['trainTaskIds'],
            'validationTaskIds': fold['validationTaskIds'], 'selectedEpoch': epoch,
            'state': rounded_state(states[epoch])} for fold, states in zip(partition['folds'], checkpoints[name])]
        artifact = make_model(name, members, selections[name], plan, manifest)
        path = args.output_dir/f'frozen-{name}.json'
        files[path.name] = write_json(path, artifact, compact=True)
        # Runtime schema is validated before any holdout encoding is permitted.
        load_model.cache_clear()
        load_model(path)
        member_hashes[name] = sha256_bytes(canonical_bytes(members))
    report = {'runId': plan['runId'], 'createdAt': utc_now(), 'selections': selections, 'cvWinner': winner,
        'folds': fold_reports, 'fullDevelopmentRefit': False, 'durationSeconds': round(time.monotonic()-started, 3),
        'scope': 'Designated-held-out-member OOF selection scores, not five-member ensemble validation or nested CV.',
        'finalLearnedEncodingOrScoringPerformed': False, 'limitations': LIMITATIONS}
    files['cv-training-report.json'] = write_json(args.output_dir/'cv-training-report.json', report)
    freeze = {'runId': plan['runId'], 'frozenAt': utc_now(), 'runPlanSha256': sha256_file(args.output_dir/'run-plan.json'),
        'sourceSha256': source_hashes(), 'partitionPlanSha256': plan['partitionPlanSha256'],
        'files': files, 'memberSha256': member_hashes, 'cvWinner': winner, 'fullDevelopmentRefit': False,
        'ensemble': {'aggregation': 'MEAN_COSINE', 'members': 5}, 'thresholds': FIXED_GATE,
        'finalLearnedEncodingOrScoringPerformed': False}
    freeze['freezeId'] = 'paired-v4-freeze-'+sha256_bytes(canonical_bytes(freeze))[:16]
    freeze_hash = write_json(args.output_dir/'model-freeze.json', freeze)
    return {'stage': 'FROZEN', 'runId': plan['runId'], 'cvWinner': winner, 'freezeSha256': freeze_hash,
        'cv': {name: {'epoch': row['selectedEpoch'], **row['pooledMetrics']} for name, row in selections.items()},
        'durationSeconds': report['durationSeconds']}


def evaluate_final(args):
    if (args.output_dir/'final-evaluation-report.json').exists():
        raise ValueError('Final assessment already completed; use its saved results.')
    plan, partition, rows, manifest = verify_plan(args)
    freeze = read_json(args.output_dir/'model-freeze.json')
    if (freeze['runId'] != plan['runId'] or freeze['sourceSha256'] != source_hashes()
            or freeze['runPlanSha256'] != sha256_file(args.output_dir/'run-plan.json')
            or freeze['partitionPlanSha256'] != plan['partitionPlanSha256'] or freeze['fullDevelopmentRefit'] is not False):
        raise ValueError('Invalid or changed freeze.')
    for name, digest in freeze['files'].items():
        if sha256_file(args.output_dir/name) != digest:
            raise ValueError('Frozen evidence changed: '+name)
    cv = read_json(args.output_dir/'cv-training-report.json')
    if freeze['cvWinner'] != select_winner(cv['selections']) or cv['cvWinner'] != freeze['cvWinner']:
        raise ValueError('CV winner changed after model selection.')
    models = {}
    for name in ORDER:
        load_model.cache_clear()
        model = load_model(args.output_dir/f'frozen-{name}.json')
        if model['candidateId'] != name or model['thresholds'] != FIXED_GATE:
            raise ValueError('Candidate identity/gate changed.')
        if sha256_bytes(canonical_bytes(model['members'])) != freeze['memberSha256'][name]:
            raise ValueError('Frozen members changed.')
        for member, fold in zip(model['members'], partition['folds']):
            if member['trainingTaskIds'] != fold['trainTaskIds'] or member['validationTaskIds'] != fold['validationTaskIds']:
                raise ValueError('Candidate fold memberships changed.')
        models[name] = model
    marker = {'runId': plan['runId'], 'freezeSha256': sha256_file(args.output_dir/'model-freeze.json'),
        'cvWinnerBeforeScoring': freeze['cvWinner'], 'startedAt': utc_now()}
    with (args.output_dir/'final-evaluation-started.json').open('x') as handle:
        json.dump(marker, handle, indent=2)
    by_id = {row['task_id']: row for row in rows}
    identifiers = partition['finalHoldoutTaskIds']
    final_rows = [by_id[value] for value in identifiers]
    graphs = graph_pairs(final_rows)
    results, individuals = {}, {}
    for name, model in models.items():
        score_matrices = []
        for member in model['members']:
            if name == 'structural_cca':
                c, j = [encode_cca(np.stack([graph_features(g) for g in side]), member['state'], language)
                        for side, language in zip(graphs, ('cobol', 'java'))]
            else:
                params = {key: np.asarray(value) for key, value in member['state']['weights'].items()}
                batches = [batch_graphs(side) for side in graphs]
                c, j = [forward(batch, params) if name == 'baseline' else forward_candidate(batch, params, name, language)
                        for batch, language in zip(batches, ('cobol', 'java'))]
            score_matrices.append(c@j.T)
        results[name] = per_query_result(np.mean(score_matrices, axis=0), identifiers)
        individuals[name] = [{'fold': member['fold'], **per_query_result(scores, identifiers)}
                             for member, scores in zip(model['members'], score_matrices)]
    results.update({name: per_query_result(scores, identifiers) for name, scores in baseline_scores(final_rows, graphs).items()})
    report = {'runId': plan['runId'], 'evaluatedAt': utc_now(), 'cvWinner': freeze['cvWinner'],
        'selection': 'Winner frozen using development-only CV before all final results; no final model selection.',
        'candidateOrder': identifiers, 'queries': 23, 'candidatesPerQuery': 23,
        'metrics': {name: value['metrics'] for name, value in results.items()}, 'results': results,
        'individualMemberResults': individuals, 'fullDevelopmentRefit': False,
        'runPlanSha256': sha256_file(args.output_dir/'run-plan.json'), 'freezeSha256': marker['freezeSha256'],
        'partitionPlanSha256': plan['partitionPlanSha256'], 'datasetSha256': manifest['sha256'],
        'cvSelections': cv['selections'], 'papers': PAPERS, 'limitations': LIMITATIONS,
        'memberScoreProvenance': 'Equal mean of the five cached member score matrices; all members retained regardless of final outcomes.'}
    report_hash = write_json(args.output_dir/'final-evaluation-report.json', report)
    winner = models[freeze['cvWinner']]
    winner.pop('_artifactSha256')
    winner['evaluation'] = {'status': 'BENCHMARK_PILOT', 'test': report['metrics'],
        'selectedCandidateId': freeze['cvWinner'], 'validation': {name: row['pooledMetrics'] for name, row in cv['selections'].items()},
        'financialDomainValidated': False, 'finalHoldout': {'tasks': 23, 'previouslyExposed': True,
            'protocolChangedAfterExposure': True, 'evaluationReportSha256': report_hash},
        'scope': 'Whole-program correspondence retrieval; no formal-equivalence accuracy claim.'}
    winner['provenance'].update({'finalEvaluationReportSha256': report_hash, 'freezeSha256': marker['freezeSha256'],
        'cvWinnerFrozenBeforeFinalEvaluation': True})
    if sha256_bytes(canonical_bytes(winner['members'])) != freeze['memberSha256'][freeze['cvWinner']]:
        raise ValueError('Deployment changed learned members.')
    model_hash = write_json(args.model_output, winner, compact=True)
    write_json(args.output_dir/'deployment-manifest.json', {'runId': plan['runId'], 'modelId': winner['id'],
        'candidateId': freeze['cvWinner'], 'modelSha256': model_hash, 'memberSha256': freeze['memberSha256'][freeze['cvWinner']],
        'membersChangedAfterFreeze': False, 'fullDevelopmentRefit': False, 'finalEvaluationReportSha256': report_hash,
        'selectionSource': 'development-only CV; frozen before final scoring'})
    return {'stage': 'FINAL_EVALUATED', 'cvWinner': freeze['cvWinner'], 'metrics': report['metrics'],
        'modelSha256': model_hash, 'reportSha256': report_hash}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument('--prepare', action='store_true')
    stage.add_argument('--train', action='store_true')
    stage.add_argument('--evaluate-final', action='store_true')
    parser.add_argument('--dataset', type=Path, default=ROOT/'evaluation/corpora/cobol-javatrans/COBOL-JavaTrans.jsonl')
    parser.add_argument('--partition-plan', type=Path, default=ROOT/'evaluation/paired-code/cv-partition-plan.json')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--model-output', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--epochs', type=int, default=250)
    parser.add_argument('--seed', type=int, default=431)
    args = parser.parse_args()
    function = prepare if args.prepare else train if args.train else evaluate_final
    print(json.dumps(function(args), allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
