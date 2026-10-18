"""Tiny graph/array checks only; never read or fit the benchmark corpus."""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from ml_engine.code_graph import CodeGraph, FEATURE_NAMES, RELATIONS
from ml_engine.structural_cca import FEAT_DIM, encode_cca, fit_cca, graph_features, validate_cca


def _unit_graph():
    x = np.zeros((4, len(FEATURE_NAMES)))
    x[0, 0] = 1
    x[1, 1] = x[1, FEATURE_NAMES.index("op_add")] = 1
    x[2, 2] = x[2, FEATURE_NAMES.index("constant_one")] = 1
    x[3, 1] = x[3, FEATURE_NAMES.index("op_return")] = 1
    edges = {relation: np.empty((0, 2), dtype=np.int64) for relation in RELATIONS}
    edges["data"] = np.array([[0, 1], [2, 1]], dtype=np.int64)
    edges["sequence"] = np.array([[1, 3]], dtype=np.int64)
    return CodeGraph(x, edges, {"task": "this-must-never-be-a-feature"})


def test_wl_features_are_node_permutation_edge_order_and_metadata_invariant():
    graph = _unit_graph()
    permutation = np.array([2, 0, 3, 1])
    reverse = np.argsort(permutation)
    changed = CodeGraph(graph.x[permutation], {
        relation: reverse[endpoints[::-1]] for relation, endpoints in graph.edges.items()
    }, {"task": "different name", "comments": "ignored"})
    before = graph_features(graph)
    np.testing.assert_array_equal(before, graph_features(changed))
    assert before.shape == (FEAT_DIM,)
    assert np.all(np.isfinite(before))
    repeated = copy.deepcopy(graph)
    repeated.edges["data"] = np.repeat(repeated.edges["data"], 2, axis=0)
    np.testing.assert_array_equal(before, graph_features(repeated))


def test_wl_features_preserve_relation_and_direction_information():
    graph = _unit_graph()
    changed_relation = copy.deepcopy(graph)
    changed_relation.edges["data"], changed_relation.edges["control"] = (
        changed_relation.edges["control"], changed_relation.edges["data"])
    assert not np.array_equal(graph_features(graph), graph_features(changed_relation))
    changed_direction = copy.deepcopy(graph)
    changed_direction.edges["data"] = changed_direction.edges["data"][:, ::-1]
    assert not np.array_equal(graph_features(graph), graph_features(changed_direction))


def test_fit_uses_only_training_means_scales_and_keeps_inference_frozen():
    training = np.array([[1., 2., 0.], [3., 2., 1.], [5., 2., 3.], [7., 2., 4.]])
    java = training * [2., 1., 3.] + [10., 2., -1.]
    state = fit_cca(training, java)
    np.testing.assert_array_equal(state["cobol"]["mean"], training.mean(axis=0))
    np.testing.assert_array_equal(state["java"]["mean"], java.mean(axis=0))
    assert state["cobol"]["scale"][1] == 1.0
    before = json.dumps(state, sort_keys=True, allow_nan=False)
    heldout_unit_fixture = np.array([1000., 10., -1000.])
    encoded = encode_cca(heldout_unit_fixture, state, "cobol")
    assert encoded.shape == (24,)
    assert np.linalg.norm(encoded) == pytest.approx(1.0)
    assert json.dumps(state, sort_keys=True, allow_nan=False) == before
    np.testing.assert_array_equal(encoded, encode_cca(heldout_unit_fixture, state, "cobol"))


def test_cca_learns_two_view_correspondence_on_small_numerical_unit_fixture():
    rng = np.random.default_rng(431)
    latent = rng.normal(size=(24, 3))
    a = latent @ rng.normal(size=(3, 7)) + np.arange(7)
    b = latent @ rng.normal(size=(3, 5)) - np.arange(5)
    state = fit_cca(a, b, regularization=.1)
    left, right = encode_cca(a, state, "cobol"), encode_cca(b, state, "java")
    assert left.shape == right.shape == (24, 24)
    np.testing.assert_allclose(np.linalg.norm(left, axis=1), 1.)
    np.testing.assert_allclose(np.linalg.norm(right, axis=1), 1.)
    # Unit-array training correspondence checks the math, never benchmark quality.
    assert np.mean(np.argmax(left @ right.T, axis=1) == np.arange(24)) > .9
    assert np.count_nonzero(np.asarray(state["cobol"]["projection"])[:, 3:]) == 0
    json.dumps(state, allow_nan=False)


def test_constant_rank_zero_views_remain_finite_fixed_width():
    state = fit_cca(np.ones((4, 8)), np.ones((4, 9)))
    np.testing.assert_array_equal(encode_cca(np.ones((2, 8)), state, "cobol"), np.zeros((2, 24)))
    assert state["canonicalCorrelations"] == []


@pytest.mark.parametrize("bad", [np.zeros(3), np.zeros((1, 3)), np.zeros((4, 0)),
                                  np.array([[0., 1.], [np.nan, 2.]])])
def test_fit_rejects_invalid_training_arrays(bad):
    with pytest.raises(ValueError):
        fit_cca(bad, bad)


@pytest.mark.parametrize("regularization", [0, -1, float("nan"), float("inf"), True])
def test_fit_rejects_invalid_ridge(regularization):
    with pytest.raises(ValueError):
        fit_cca(np.eye(3), np.eye(3), regularization=regularization)


@pytest.mark.parametrize("output", [0, -1, 1.2, True])
def test_fit_rejects_invalid_output_width(output):
    with pytest.raises(ValueError):
        fit_cca(np.eye(3), np.eye(3), output=output)


def test_fit_rejects_unpaired_rows_and_encoder_rejects_bad_input():
    with pytest.raises(ValueError):
        fit_cca(np.eye(3), np.eye(4))
    state = fit_cca(np.eye(3), np.eye(3))
    for values, language in ((np.zeros(4), "cobol"), (np.ones(3), "python"),
                              (np.array([np.nan, 0., 0.]), "java")):
        with pytest.raises(ValueError):
            encode_cca(values, state, language)


def test_validator_checks_fixed_runtime_schema_and_finite_state():
    unit = np.zeros((4, FEAT_DIM))
    unit[:, :4] = np.eye(4)
    model = fit_cca(unit, unit)
    validate_cca(model)
    corruptions = []
    wrong_width = copy.deepcopy(model); wrong_width["output"] = 23; corruptions.append(wrong_width)
    wrong_feature = copy.deepcopy(model); wrong_feature["cobol"]["mean"].pop(); corruptions.append(wrong_feature)
    bad_scale = copy.deepcopy(model); bad_scale["java"]["scale"][0] = 0; corruptions.append(bad_scale)
    bad_projection = copy.deepcopy(model); bad_projection["java"]["projection"][0][0] = float("nan"); corruptions.append(bad_projection)
    for corruption in corruptions:
        with pytest.raises(ValueError):
            validate_cca(corruption)


def test_graph_feature_validation_rejects_invalid_edges_and_nonfinite_semantics():
    for mutation in ("bad_index", "bad_shape", "float_edges", "missing_relation", "nan"):
        graph = _unit_graph()
        if mutation == "bad_index": graph.edges["data"][0, 0] = 50
        elif mutation == "bad_shape": graph.edges["data"] = np.zeros(2, dtype=int)
        elif mutation == "float_edges": graph.edges["data"] = graph.edges["data"].astype(float)
        elif mutation == "missing_relation": del graph.edges["data"]
        else: graph.x[0, 0] = float("nan")
        with pytest.raises(ValueError):
            graph_features(graph)
