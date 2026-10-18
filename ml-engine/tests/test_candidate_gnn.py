"""Numerical candidate regressions on tiny unit graphs, never the real corpus."""
from __future__ import annotations

import numpy as np
import pytest

from ml_engine.candidate_gnn import (
    VARIANTS,
    augment_batch,
    backward_candidate,
    forward_candidate,
    initialise_candidate,
)
from ml_engine.code_graph import CodeGraph, FEATURE_NAMES, RELATIONS
from ml_engine.paired_gnn import batch_graphs, forward, initialise, paired_loss


def _unit_graphs():
    rng = np.random.default_rng(719)
    graphs = []
    for count in (3, 5):
        # Dense random test features avoid max-readout ties in finite differences.
        features = rng.uniform(-0.4, 0.8, (count, len(FEATURE_NAMES)))
        forward_edges = [(index, index + 1) for index in range(count - 1)]
        edges = np.asarray(forward_edges + [(right, left) for left, right in forward_edges], dtype=np.int64)
        graphs.append(CodeGraph(features, {relation: edges.copy() for relation in RELATIONS}, {}))
    return graphs


@pytest.mark.parametrize('variant', VARIANTS)
@pytest.mark.parametrize('language', ('cobol', 'java'))
def test_forward_is_unit_length_and_backward_matches_all_parameter_shapes(variant, language):
    params = initialise_candidate(variant)
    values, cache = forward_candidate(batch_graphs(_unit_graphs()), params, variant, language, True)
    assert values.shape == (2, 24)
    np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1, atol=1e-12)
    gradients = backward_candidate(np.ones_like(values), cache, params, variant, language)
    assert set(gradients) == set(params)
    for name, parameter in params.items():
        assert gradients[name].shape == parameter.shape
        assert np.isfinite(gradients[name]).all()


@pytest.mark.parametrize('variant', VARIANTS)
@pytest.mark.parametrize('language', ('cobol', 'java'))
def test_analytic_gradients_match_finite_differences(variant, language):
    batch = batch_graphs(_unit_graphs())
    params = initialise_candidate(variant, seed=23)
    upstream = np.random.default_rng(42).normal(size=(2, 24))
    _, cache = forward_candidate(batch, params, variant, language, True)
    gradients = backward_candidate(upstream, cache, params, variant, language)
    readout = f'readout_{language}' if variant == 'language_heads' else 'readout'
    coordinates = [('W1_self', (0, 0)), ('W2_data', (0, 1)), (readout, (0, 2))]
    if variant == 'count_readout':
        # Check max and explicit graph-size readout coordinates as well.
        coordinates.extend([('readout', (24, 2)), ('readout', (144, 3))])
    step = 1e-6
    for name, coordinate in coordinates:
        original = params[name][coordinate]
        params[name][coordinate] = original + step
        positive = np.sum(forward_candidate(batch, params, variant, language) * upstream)
        params[name][coordinate] = original - step
        negative = np.sum(forward_candidate(batch, params, variant, language) * upstream)
        params[name][coordinate] = original
        numeric = (positive - negative) / (2 * step)
        assert gradients[name][coordinate] == pytest.approx(numeric, rel=2e-5, abs=2e-7), (name, coordinate)


def test_graph_regularized_is_exact_original_encoder_until_training_augmentation():
    batch = batch_graphs(_unit_graphs())
    expected = forward(batch, initialise(seed=431))
    actual = forward_candidate(batch, initialise_candidate('graph_regularized'), 'graph_regularized', 'cobol')
    np.testing.assert_array_equal(actual, expected)


def test_language_heads_share_initial_alignment_but_receive_separate_gradients():
    batch = batch_graphs(_unit_graphs())
    params = initialise_candidate('language_heads')
    expected = forward(batch, initialise(seed=431))
    cobol, cobol_cache = forward_candidate(batch, params, 'language_heads', 'cobol', True)
    java, java_cache = forward_candidate(batch, params, 'language_heads', 'java', True)
    np.testing.assert_array_equal(cobol, expected)
    np.testing.assert_array_equal(java, expected)
    assert not np.shares_memory(params['readout_cobol'], params['readout_java'])
    _, grad_cobol, grad_java = paired_loss(cobol, java)
    cobol_grads = backward_candidate(grad_cobol, cobol_cache, params, 'language_heads', 'cobol')
    java_grads = backward_candidate(grad_java, java_cache, params, 'language_heads', 'java')
    np.testing.assert_array_equal(cobol_grads['readout_java'], 0)
    np.testing.assert_array_equal(java_grads['readout_cobol'], 0)
    assert np.linalg.norm(cobol_grads['readout_cobol']) > 0
    assert np.linalg.norm(java_grads['readout_java']) > 0


def test_count_readout_retains_means_maxima_and_size_normalised_sums():
    batch = batch_graphs(_unit_graphs())
    params = initialise_candidate('count_readout')
    _, (layers, pooled, _, _, _) = forward_candidate(batch, params, 'count_readout', 'cobol', True)
    _, _, groups, sizes = batch
    assert pooled.shape == (2, 145)
    for index, (_, activations, _) in enumerate(layers):
        offset = index * 72
        for group, size in enumerate(sizes):
            local = activations[groups == group]
            np.testing.assert_allclose(pooled[group, offset:offset + 24], local.mean(axis=0))
            np.testing.assert_allclose(pooled[group, offset + 24:offset + 48], local.max(axis=0))
            np.testing.assert_allclose(pooled[group, offset + 48:offset + 72], local.sum(axis=0) / np.sqrt(size))
    np.testing.assert_allclose(pooled[:, -1], np.log1p(sizes) / 10)


def test_count_readout_is_invariant_to_node_order():
    graphs = _unit_graphs()
    permuted = []
    for graph in graphs:
        order = np.arange(len(graph.x))[::-1]
        inverse = np.argsort(order)
        permuted.append(CodeGraph(graph.x[order], {name: inverse[edges] for name, edges in graph.edges.items()}, {}))
    params = initialise_candidate('count_readout')
    original = forward_candidate(batch_graphs(graphs), params, 'count_readout', 'java')
    reordered = forward_candidate(batch_graphs(permuted), params, 'count_readout', 'java')
    np.testing.assert_allclose(original, reordered, rtol=0, atol=1e-12)


class _FixedRandom:
    def random(self, count):
        # Deterministically drop every other undirected link so the test checks
        # both dropped and retained pairs without relying on stochastic luck.
        return np.where(np.arange(count) % 2, 0.5, 0.05)


def test_augmentation_is_pure_drops_reverse_pairs_together_and_reweights_means():
    original = batch_graphs(_unit_graphs())
    snapshot = (original[0].copy(), {r: (e.copy(), w.copy()) for r, (e, w) in original[1].items()},
                original[2].copy(), original[3].copy())
    augmented = augment_batch(original, _FixedRandom())
    for source, unchanged in ((original[0], snapshot[0]), (original[2], snapshot[2]), (original[3], snapshot[3])):
        np.testing.assert_array_equal(source, unchanged)
    for index in (0, 2, 3):
        np.testing.assert_array_equal(original[index], augmented[index])
        assert not np.shares_memory(original[index], augmented[index])
    for relation in RELATIONS:
        for part in (0, 1):
            np.testing.assert_array_equal(original[1][relation][part], snapshot[1][relation][part])
            assert not np.shares_memory(original[1][relation][part], augmented[1][relation][part])
    for relation in ('data', 'control'):
        np.testing.assert_array_equal(original[1][relation][0], augmented[1][relation][0])
        np.testing.assert_array_equal(original[1][relation][1], augmented[1][relation][1])
    edges, weights = augmented[1]['sequence']
    assert 0 < len(edges) < len(original[1]['sequence'][0])
    retained = set(map(tuple, edges))
    assert all((right, left) in retained for left, right in retained)
    degrees = np.bincount(edges[:, 0], minlength=len(original[0]))
    np.testing.assert_allclose(weights, 1 / degrees[edges[:, 0]])


def test_augmentation_is_reproducible_and_empty_edges_are_supported():
    batch = batch_graphs(_unit_graphs())
    first = augment_batch(batch, np.random.default_rng(41))
    second = augment_batch(batch, np.random.default_rng(41))
    np.testing.assert_array_equal(first[1]['sequence'][0], second[1]['sequence'][0])
    empty_batch = batch_graphs(_unit_graphs(), message_passing=False)
    augmented = augment_batch(empty_batch, np.random.default_rng(41))
    assert augmented[1]['sequence'][0].shape == (0, 2)
    assert augmented[1]['sequence'][1].shape == (0,)


@pytest.mark.parametrize('variant', VARIANTS)
def test_candidate_rejects_unknown_language(variant):
    with pytest.raises(ValueError, match='language'):
        forward_candidate(batch_graphs(_unit_graphs()), initialise_candidate(variant), variant, 'python')


def test_initialisation_rejects_unknown_variant():
    with pytest.raises(ValueError, match='variant'):
        initialise_candidate('nonexistent')
