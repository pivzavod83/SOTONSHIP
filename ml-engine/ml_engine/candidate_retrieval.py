"""Inference for CV-selected paired-source models, independent of formal proof."""
from __future__ import annotations

from collections import Counter
import numpy as np

from .code_graph import CodeGraph

CANDIDATES = ('baseline', 'count_readout', 'language_heads', 'structural_cca', 'graph_regularized')


def member_embedding(graph: CodeGraph, member: dict, candidate: str, language: str) -> np.ndarray:
    if language not in ('cobol', 'java'):
        raise ValueError('paired retrieval requires the explicit source language')
    if candidate == 'structural_cca':
        from .structural_cca import graph_features, encode_cca
        return encode_cca(graph_features(graph), member['state'], language)
    from .paired_gnn import batch_graphs, forward
    params = {name: np.asarray(value, dtype=float) for name, value in member['state']['weights'].items()}
    batch = batch_graphs([graph])
    if candidate == 'baseline':
        return forward(batch, params)[0]
    from .candidate_gnn import forward_candidate
    return forward_candidate(batch, params, candidate, language)[0]


def encode_candidate(graph: CodeGraph, model: dict, language: str) -> np.ndarray:
    vectors = [member_embedding(graph, member, model['candidateId'], language) for member in model['members']]
    return np.concatenate(vectors) / np.sqrt(5)


def validate_candidate_model(model: dict) -> None:
    from .paired_gnn import _validate_weights, initialise
    from .candidate_gnn import initialise_candidate
    from .structural_cca import validate_cca
    candidate = model.get('candidateId')
    if candidate not in CANDIDATES:
        raise ValueError('unknown selected candidate')
    if model.get('ensemble') != {'aggregation': 'MEAN_COSINE', 'members': 5}:
        raise ValueError('selected model requires five equal mean-cosine members')
    training = model.get('training', {})
    epoch = training.get('selectedEpoch')
    if (training.get('fullDevelopmentRefit') is not False or isinstance(epoch, bool)
            or not isinstance(epoch, int) or epoch < 1 or 'weights' in model):
        raise ValueError('invalid selected ensemble fitting protocol')
    members = model.get('members')
    if not isinstance(members, list) or len(members) != 5:
        raise ValueError('exactly five retained fold members required')
    development, validation_counts = None, Counter()
    for fold, member in enumerate(members, 1):
        if (not isinstance(member, dict) or type(member.get('fold')) is not int
                or type(member.get('selectedEpoch')) is not int
                or member['fold'] != fold or member['selectedEpoch'] != epoch):
            raise ValueError('member fold/common epoch mismatch')
        partitions = []
        for field, size in (('trainingTaskIds', 96), ('validationTaskIds', 24)):
            values = member.get(field)
            if (not isinstance(values, list) or len(values) != size
                    or any(not isinstance(value, str) or not value for value in values)
                    or len(set(values)) != size):
                raise ValueError('each member requires unique 96/24 task memberships')
            partitions.append(set(values))
        fit, validation = partitions
        if fit & validation or (development is not None and fit | validation != development):
            raise ValueError('folds must partition the same 120 development tasks')
        development = fit | validation
        validation_counts.update(validation)
        state = member.get('state')
        if not isinstance(state, dict):
            raise ValueError('missing retained model state')
        if candidate == 'structural_cca':
            validate_cca(state)
            if state['trainingRows'] != 96 or epoch != 1:
                raise ValueError('CCA must retain its one closed-form fit on 96 pairs')
        else:
            expected = initialise() if candidate == 'baseline' else initialise_candidate(candidate)
            _validate_weights(state.get('weights'), expected)
    if set(validation_counts) != development or any(count != 1 for count in validation_counts.values()):
        raise ValueError('each development task must be excluded by exactly one member')
