"""Small, explicitly named retrieval candidates for development-fold comparison.

These variants use the unchanged heuristic code-graph extractor and the original
two relation-aware message-passing layers. ``count_readout`` is inspired by
multiset/sum readouts; it is not an implementation of GIN. ``language_heads``
uses a shared encoder and independently learned target/source projection heads.
``graph_regularized`` has the original architecture; its training caller can
use ``augment_batch`` on fitting graphs only. No variant changes pair labels.
"""
from __future__ import annotations

import numpy as np

from .code_graph import RELATIONS
from .paired_gnn import (
    aggregate,
    aggregate_backward,
    backward,
    forward,
    initialise,
)


VARIANTS = ('count_readout', 'language_heads', 'graph_regularized')


def _validate_variant(variant: str) -> None:
    if variant not in VARIANTS:
        raise ValueError(f'unknown candidate variant: {variant}')


def _validate_language(language: str) -> None:
    if language not in ('cobol', 'java'):
        raise ValueError('candidate language must be cobol or java')


def initialise_candidate(variant: str, seed: int = 431) -> dict[str, np.ndarray]:
    """Create independent parameters without reading any training/evaluation data."""
    _validate_variant(variant)
    params = initialise(seed=seed)
    if variant == 'count_readout':
        hidden, output = params['readout'].shape[0] // 2, params['readout'].shape[1]
        # Two layers, each with mean, max, and size-normalised sum, followed by
        # one explicit log-count coordinate. This preserves node multiplicity.
        rows = 6 * hidden + 1
        params['readout'] = np.random.default_rng(seed + 719).normal(
            0, np.sqrt(1 / rows), (rows, output)
        )
    elif variant == 'language_heads':
        # Equal initial heads preserve the baseline's initial cross-language
        # alignment; their separate gradients then learn language-specific maps.
        shared_initial_head = params.pop('readout')
        params['readout_cobol'] = shared_initial_head.copy()
        params['readout_java'] = shared_initial_head.copy()
    return params


def _count_forward(batch, params, need_cache=False):
    x, edges, groups, sizes = batch
    hidden = params['b1'].shape[0]
    h = x
    cache = []
    pooled = []
    starts = np.r_[0, np.cumsum(sizes[:-1])]
    for layer in (1, 2):
        inputs = {'self': h, **{relation: aggregate(h, *edges[relation]) for relation in RELATIONS}}
        pre = sum(values @ params[f'W{layer}_{relation}'] for relation, values in inputs.items())
        h = np.tanh(pre + params[f'b{layer}'])
        sums = np.zeros((len(sizes), hidden))
        np.add.at(sums, groups, h)
        maxima = np.empty_like(sums)
        argmax = np.empty((len(sizes), hidden), dtype=np.int64)
        for index, (start, size) in enumerate(zip(starts, sizes)):
            local = h[start:start + size]
            maximum_indices = np.argmax(local, axis=0)
            argmax[index] = start + maximum_indices
            maxima[index] = local[maximum_indices, np.arange(hidden)]
        pooled.extend((sums / sizes[:, None], maxima, sums / np.sqrt(sizes[:, None])))
        cache.append((inputs, h, argmax))
    count = np.log1p(sizes[:, None]) / 10
    p = np.concatenate((*pooled, count), axis=1)
    z = p @ params['readout']
    norms = np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-9)
    values = z / norms
    return (values, (cache, p, z, norms, batch)) if need_cache else values


def forward_candidate(batch, params, variant: str, language: str, need_cache=False):
    """Encode a monolingual graph batch into unit retrieval embeddings."""
    _validate_variant(variant)
    _validate_language(language)
    if variant == 'count_readout':
        return _count_forward(batch, params, need_cache)
    if variant == 'language_heads':
        view = {key: value for key, value in params.items() if not key.startswith('readout_')}
        view['readout'] = params[f'readout_{language}']
        return forward(batch, view, need_cache)
    return forward(batch, params, need_cache)


def _count_backward(grad, saved, params):
    cache, p, z, norms, batch = saved
    _, edges, groups, sizes = batch
    values = z / norms
    dz = (grad - values * np.sum(grad * values, axis=1, keepdims=True)) / norms
    grads = {'readout': p.T @ dz}
    dp = dz @ params['readout'].T
    hidden = params['b1'].shape[0]
    dh = np.zeros_like(cache[1][1])
    for layer in (2, 1):
        inputs, h, argmax = cache[layer - 1]
        local = dp[:, (layer - 1) * 3 * hidden:layer * 3 * hidden]
        dh += local[:, :hidden][groups] / sizes[groups, None]
        dh += local[:, 2 * hidden:][groups] / np.sqrt(sizes[groups, None])
        # np.argmax chooses the first node on a tie, making the subgradient
        # deterministic. Columns are separate hidden coordinates.
        np.add.at(dh, (argmax.ravel(), np.tile(np.arange(hidden), len(sizes))),
                  local[:, hidden:2 * hidden].ravel())
        dpre = dh * (1 - h * h)
        grads[f'b{layer}'] = dpre.sum(axis=0)
        previous = np.zeros_like(inputs['self'])
        for relation, inputs_for_relation in inputs.items():
            grads[f'W{layer}_{relation}'] = inputs_for_relation.T @ dpre
            local_grad = dpre @ params[f'W{layer}_{relation}'].T
            previous += local_grad if relation == 'self' else aggregate_backward(local_grad, *edges[relation])
        dh = previous
    return grads


def backward_candidate(grad, cache, params, variant: str, language: str):
    """Return gradients for every parameter, including the unused language head."""
    _validate_variant(variant)
    _validate_language(language)
    if variant == 'count_readout':
        return _count_backward(grad, cache, params)
    if variant == 'language_heads':
        view = {key: value for key, value in params.items() if not key.startswith('readout_')}
        view['readout'] = params[f'readout_{language}']
        grads = backward(grad, cache, view)
        selected = grads.pop('readout')
        grads['readout_cobol'] = selected if language == 'cobol' else np.zeros_like(params['readout_cobol'])
        grads['readout_java'] = selected if language == 'java' else np.zeros_like(params['readout_java'])
        return grads
    return backward(grad, cache, params)


def augment_batch(batch, rng: np.random.Generator):
    """Copy a fitting batch and drop 10% of undirected sequence links in expectation.

    The original graph and all feature/data/control values remain intact. Both
    directions of a sequence link share one random decision. Recompute incoming
    means after dropping edges, rather than retaining stale degree weights.
    The caller must never augment validation or final-evaluation graphs.
    """
    x, edges, groups, sizes = batch
    copied_edges = {relation: (indices.copy(), weights.copy())
                    for relation, (indices, weights) in edges.items()}
    sequence, _ = copied_edges['sequence']
    if len(sequence):
        canonical = np.sort(sequence, axis=1)
        pairs, inverse = np.unique(canonical, axis=0, return_inverse=True)
        keep = rng.random(len(pairs)) >= 0.10
        retained = sequence[keep[inverse]].copy()
        degrees = np.bincount(retained[:, 0], minlength=len(x))
        weights = 1 / np.maximum(1, degrees)[retained[:, 0]]
        copied_edges['sequence'] = retained, weights
    return x.copy(), copied_edges, groups.copy(), sizes.copy()
