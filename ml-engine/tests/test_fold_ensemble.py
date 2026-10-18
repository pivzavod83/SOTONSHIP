"""Numerical/protocol regression tests for retained cross-validation members.

Only tiny unit-test graphs and mocked numerical fitting are evaluated here.
The reserved corpus is never fitted, encoded, or scored by this test module.
Saved final evaluation artifacts are checked arithmetically when available.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ml_engine import paired_gnn
from ml_engine.code_graph import CodeGraph, FEATURE_NAMES, RELATIONS, build_graph


ROOT = Path(__file__).resolve().parents[1]


def _pipeline():
    return importlib.import_module("scripts.train_paired_gnn_fold_ensemble")


def _unit_artifact():
    development = [f"Unit/{index}" for index in range(120)]
    members = []
    for index in range(5):
        validation = development[index * 24:(index + 1) * 24]
        parameters = paired_gnn.initialise(seed=431 + index)
        parameters["b1"][0] = index + 1
        members.append({
            "fold": index + 1,
            "weights": {key: value.tolist() for key, value in parameters.items()},
            "trainingTaskIds": [task for task in development if task not in validation],
            "validationTaskIds": validation,
            "selectedEpoch": 10,
        })
    return {
        "id": "unit-only-fold-ensemble",
        "kind": "FOLD_ENSEMBLE",
        "ensemble": {"aggregation": "MEAN_COSINE", "members": 5},
        "featureNames": list(FEATURE_NAMES),
        "relations": list(RELATIONS),
        "members": members,
        "training": {
            "dataset": "Unit-test metadata; never corpus training",
            "splitCounts": {"development": 120, "finalHoldout": 23},
            "crossValidation": {"folds": 5, "trainPerFold": 96, "validationPerFold": 24},
            "fullDevelopmentRefit": False,
            "selectedEpoch": 10,
        },
        "thresholds": {"minimumSimilarity": 1.0, "minimumMargin": 2.0},
        "evaluation": {"status": "UNIT_TEST_ONLY"},
        "limitations": ["Synthetic unit-test fixture, never an accuracy benchmark."],
    }


def _load_unit_artifact(tmp_path, artifact):
    path = tmp_path / "unit-model.json"
    path.write_text(json.dumps(artifact))
    paired_gnn.load_model.cache_clear()
    return paired_gnn.load_model(path)


def _marker_graph(marker):
    features = np.zeros((1, len(FEATURE_NAMES)))
    features[0, 0] = marker
    return CodeGraph(features, {relation: np.empty((0, 2), dtype=int) for relation in RELATIONS}, {})


def test_embedding_is_mean_of_member_cosines_not_mean_of_incompatible_coordinates(tmp_path, monkeypatch):
    model = _load_unit_artifact(tmp_path, _unit_artifact())

    def member_forward(batch, parameters, need_cache=False):
        assert need_cache is False
        member = int(parameters["b1"][0]) - 1
        query = batch[0][0, 0] == 1
        vector = np.zeros((1, 24))
        # Three members agree; two disagree in a different embedding basis.
        vector[0, 0 if member < 3 else 1] = 1 if query or member < 3 else -1
        return vector

    monkeypatch.setattr(paired_gnn, "forward", member_forward)
    query = paired_gnn.encode_graph(_marker_graph(1), model)
    candidate = paired_gnn.encode_graph(_marker_graph(2), model)
    assert query.shape == candidate.shape == (5 * 24,)
    assert np.linalg.norm(query) == pytest.approx(1.0)
    assert np.linalg.norm(candidate) == pytest.approx(1.0)
    assert query @ candidate == pytest.approx((1 + 1 + 1 - 1 - 1) / 5)

    # Averaging independently trained coordinates before taking cosine gives a
    # different answer and would silently change the declared ensemble rule.
    average_query = np.array([3 / 5, 2 / 5])
    average_candidate = np.array([3 / 5, -2 / 5])
    naive_cosine = (average_query @ average_candidate) / (
        np.linalg.norm(average_query) * np.linalg.norm(average_candidate)
    )
    assert abs(float(query @ candidate) - naive_cosine) > 0.1


def test_runtime_embedding_dot_products_match_five_independent_numpy_encoders(tmp_path):
    model = _load_unit_artifact(tmp_path, _unit_artifact())
    graph_a = build_graph("class Example { int f(int a) { return a + 1; } }", "java")
    graph_b = build_graph("class Example { int f(int a) { return a * 2; } }", "java")
    expected = []
    for member in model["members"]:
        parameters = {key: np.asarray(value) for key, value in member["weights"].items()}
        vectors = paired_gnn.forward(paired_gnn.batch_graphs([graph_a, graph_b]), parameters)
        expected.append(float(vectors[0] @ vectors[1]))
    first = paired_gnn.encode_graph(graph_a, model)
    second = paired_gnn.encode_graph(graph_b, model)
    assert first @ second == pytest.approx(float(np.mean(expected)), abs=1e-12)


def test_evaluation_scoring_matches_runtime_ensemble_on_unit_graphs(tmp_path):
    pipeline = _pipeline()
    model = _load_unit_artifact(tmp_path, _unit_artifact())
    query_graphs = [
        build_graph(f"class Example {{ int f(int a) {{ return a + {constant}; }} }}", "java")
        for constant in (1, 2, 3)
    ]
    candidate_graphs = [
        build_graph(f"class Example {{ int f(int a) {{ return a * {constant}; }} }}", "java")
        for constant in (1, 2, 3)
    ]
    before = json.dumps(model["members"], sort_keys=True)
    scores = pipeline.score_ensemble((query_graphs, candidate_graphs), model["members"])
    runtime_query = np.stack([paired_gnn.encode_graph(graph, model) for graph in query_graphs])
    runtime_candidate = np.stack([paired_gnn.encode_graph(graph, model) for graph in candidate_graphs])
    np.testing.assert_allclose(scores, runtime_query @ runtime_candidate.T, rtol=0, atol=1e-12)
    assert json.dumps(model["members"], sort_keys=True) == before


@pytest.mark.parametrize("corruption", [
    "too_few_members", "too_many_members", "missing_member_weights", "wrong_weight_keys",
    "wrong_weight_shape", "nan_weight", "infinite_weight", "unknown_aggregation",
    "duplicate_training_id", "overlapping_validation", "different_development_union",
    "repeated_validation_fold", "duplicate_fold", "missing_refit_policy", "full_refit",
    "root_weights", "invalid_epoch", "mixed_member_epoch",
])
def test_loading_rejects_malformed_ensemble_members(tmp_path, corruption):
    artifact = _unit_artifact()
    if corruption == "too_few_members":
        artifact["members"].pop()
    elif corruption == "too_many_members":
        artifact["members"].append(copy.deepcopy(artifact["members"][0]))
    elif corruption == "missing_member_weights":
        del artifact["members"][0]["weights"]
    elif corruption == "wrong_weight_keys":
        del artifact["members"][0]["weights"]["readout"]
    elif corruption == "wrong_weight_shape":
        artifact["members"][0]["weights"]["readout"] = [[0.0]]
    elif corruption == "nan_weight":
        artifact["members"][0]["weights"]["b1"][0] = float("nan")
    elif corruption == "infinite_weight":
        artifact["members"][0]["weights"]["b1"][0] = float("inf")
    elif corruption == "unknown_aggregation":
        artifact["ensemble"]["aggregation"] = "AVERAGE_UNALIGNED_EMBEDDINGS"
    elif corruption == "duplicate_training_id":
        artifact["members"][0]["trainingTaskIds"][1] = artifact["members"][0]["trainingTaskIds"][0]
    elif corruption == "overlapping_validation":
        artifact["members"][0]["validationTaskIds"][0] = artifact["members"][0]["trainingTaskIds"][0]
    elif corruption == "different_development_union":
        artifact["members"][1]["trainingTaskIds"][0] = "Reserved/new-task"
    elif corruption == "repeated_validation_fold":
        artifact["members"][1]["validationTaskIds"] = artifact["members"][0]["validationTaskIds"][:]
        artifact["members"][1]["trainingTaskIds"] = artifact["members"][0]["trainingTaskIds"][:]
    elif corruption == "duplicate_fold":
        artifact["members"][1]["fold"] = 1
    elif corruption == "missing_refit_policy":
        del artifact["training"]["fullDevelopmentRefit"]
    elif corruption == "full_refit":
        artifact["training"]["fullDevelopmentRefit"] = True
    elif corruption == "root_weights":
        artifact["weights"] = artifact["members"][0]["weights"]
    elif corruption == "invalid_epoch":
        artifact["members"][0]["selectedEpoch"] = 0
    elif corruption == "mixed_member_epoch":
        artifact["members"][0]["selectedEpoch"] = 11
    with pytest.raises((ValueError, KeyError)):
        _load_unit_artifact(tmp_path, artifact)


def test_fold_checkpoints_keep_fresh_parameters_optimizer_and_no_120_pair_fit(monkeypatch):
    pipeline = _pipeline()
    graphs = ([f"C{index}" for index in range(120)] + ["HOLDOUT_C"],
              [f"J{index}" for index in range(120)] + ["HOLDOUT_J"])
    parameters_seen = []
    optimizer_seen = []
    batches_seen = []

    def fake_batch(selected, message_passing):
        assert len(selected) in (24, 96), "No fitting or gallery batch may contain all 120."
        assert all("HOLDOUT" not in graph for graph in selected)
        batches_seen.append(list(selected))
        return selected

    def fake_initialise(seed):
        parameters = {"weight": np.array([float(seed)])}
        parameters_seen.append(parameters)
        return parameters

    def fake_forward(batch, parameters, need_cache=False):
        vectors = np.tile(np.array([[1.0, 0.0]]), (len(batch), 1))
        return (vectors, None) if need_cache else vectors

    def fake_backward(gradient, saved, parameters):
        return {"weight": np.zeros_like(parameters["weight"])}

    def fake_adam(parameters, first, second, gradients, epoch):
        if epoch == 1:
            np.testing.assert_array_equal(first["weight"], [0.0])
            np.testing.assert_array_equal(second["weight"], [0.0])
            assert first["weight"] is not second["weight"]
            optimizer_seen.append((first, second))
        parameters["weight"] += 1
        first["weight"] += 1
        second["weight"] += 2

    for name, value in (("batch_graphs", fake_batch), ("initialise", fake_initialise),
                        ("forward", fake_forward), ("backward", fake_backward),
                        ("adam_step", fake_adam)):
        monkeypatch.setattr(pipeline, name, value)

    retained = []
    for fold in range(5):
        validation = list(range(fold * 24, (fold + 1) * 24))
        training = sorted(set(range(120)) - set(validation))
        history, checkpoints = pipeline.fit_fold_checkpoints(
            graphs, training, validation, seed=431, epochs=2, message_passing=True,
        )
        assert [record["epoch"] for record in history] == [1, 2]
        np.testing.assert_array_equal(checkpoints[1]["weight"], [432.0])
        np.testing.assert_array_equal(checkpoints[2]["weight"], [433.0])
        assert not np.shares_memory(checkpoints[1]["weight"], checkpoints[2]["weight"])
        assert not np.shares_memory(checkpoints[2]["weight"], parameters_seen[-1]["weight"])
        retained.append(checkpoints)

    assert len(parameters_seen) == len(optimizer_seen) == len(retained) == 5
    assert len({id(parameters["weight"]) for parameters in parameters_seen}) == 5
    assert len({id(first["weight"]) for first, _ in optimizer_seen}) == 5
    assert len(batches_seen) == 20  # Separate fitting/validation COBOL and Java batches.
    assert all(len(batch) in (24, 96) for batch in batches_seen)


def test_fold_checkpoints_reject_training_validation_overlap():
    pipeline = _pipeline()
    with pytest.raises(ValueError, match="disjoint"):
        pipeline.fit_fold_checkpoints(([], []), [0, 1], [1, 2], seed=431, epochs=1, message_passing=True)


def test_training_orchestration_retains_only_five_declared_folds_without_full_refit(tmp_path, monkeypatch):
    pipeline = _pipeline()
    legacy_pipeline = importlib.import_module("scripts.train_paired_gnn_cv")
    artifact = _unit_artifact()
    development = [f"Unit/{index}" for index in range(120)]
    reserved = [f"HOLDOUT/{index}" for index in range(23)]
    partition = {
        "developmentTaskIds": development, "finalHoldoutTaskIds": reserved,
        "folds": [{"fold": member["fold"], "trainTaskIds": member["trainingTaskIds"],
                   "validationTaskIds": member["validationTaskIds"]} for member in artifact["members"]],
    }
    args = SimpleNamespace(output_dir=tmp_path, partition_plan=tmp_path / "partition.json", seed=431, epochs=2)
    pipeline.write_json(args.partition_plan, partition)
    run_plan = {
        "runId": "unit-orchestration", "partitionPlanSha256": pipeline.sha256_file(args.partition_plan),
        "configuration": {"seed": 431, "epochsBudget": 2, "selection": "unit OOF only",
                          "ensemble": {"aggregation": "MEAN_COSINE", "members": 5}},
        "previousModels": {"unit": {"sha256": "not-loaded-by-training"}}, "priorExposure": {},
    }
    pipeline.write_json(tmp_path / "run-plan.json", run_plan)
    rows = [{"task_id": identifier} for identifier in development + reserved]
    manifest = {"sha256": "unit-not-a-real-corpus", "commit": "unit"}
    monkeypatch.setattr(pipeline, "verify_run_plan", lambda args: (run_plan, partition, rows, manifest))
    seen_graph_sources, seen_folds = [], []

    def fake_graphs(selected_rows):
        identifiers = [row["task_id"] for row in selected_rows]
        assert identifiers == development
        assert not set(identifiers) & set(reserved)
        seen_graph_sources.append(identifiers)
        return ([f"C:{task}" for task in identifiers], [f"J:{task}" for task in identifiers])

    def fake_fit(graphs, training, validation, *, seed, epochs, message_passing):
        assert len(training) == 96 and len(validation) == 24
        assert not set(training) & set(validation)
        assert sorted(training + validation) == list(range(120))
        seen_folds.append((training[:], validation[:], message_passing))
        history = [{"epoch": epoch, "trainLoss": 1.0, "validationLoss": 1.0,
                    "ranks": [1] * 24, **pipeline.rank_metrics([1] * 24, 24)} for epoch in (1, 2)]
        return history, {epoch: {"unit_weight": np.array([float(epoch)])} for epoch in (1, 2)}

    def prohibit_full_fit(*args, **kwargs):
        pytest.fail("No model may be fitted or refitted on all 120 development pairs.")

    def fake_baselines(selected_rows, selected_graphs):
        assert len(selected_rows) == len(selected_graphs[0]) == len(selected_graphs[1]) == 24
        assert not {row["task_id"] for row in selected_rows} & set(reserved)
        return {label: np.eye(24) for label in ("nameMatching", "semanticHistogram")}

    monkeypatch.setattr(pipeline, "graph_pairs", fake_graphs)
    monkeypatch.setattr(pipeline, "fit_fold_checkpoints", fake_fit)
    monkeypatch.setattr(pipeline, "baseline_scores", fake_baselines)
    monkeypatch.setattr(pipeline, "source_hashes", lambda: {"trainer": "unit"})
    monkeypatch.setattr(pipeline, "fit_full", prohibit_full_fit, raising=False)
    monkeypatch.setattr(legacy_pipeline, "fit_full", prohibit_full_fit)
    result = pipeline.train(args)
    assert result["stage"] == "FROZEN"
    assert result["fullDevelopmentRefit"] is False
    assert seen_graph_sources == [development]
    assert len(seen_folds) == 10  # Five GNN folds and five matched ablation folds.
    assert [messages for _, _, messages in seen_folds] == [True, False] * 5
    freeze = json.loads((tmp_path / "model-freeze.json").read_text())
    assert freeze["fullDevelopmentRefit"] is False
    assert freeze["finalHoldoutLearnedEncodingOrScoringPerformed"] is False
    for filename in ("frozen-checkpoint.json", "frozen-no-message-checkpoint.json"):
        saved = json.loads((tmp_path / filename).read_text())
        assert len(saved["members"]) == 5
        assert "weights" not in saved
        assert saved["training"]["fullDevelopmentRefit"] is False
        for member, declared in zip(saved["members"], partition["folds"]):
            assert member["trainingTaskIds"] == declared["trainTaskIds"]
            assert member["validationTaskIds"] == declared["validationTaskIds"]
            assert not set(member["trainingTaskIds"] + member["validationTaskIds"]) & set(reserved)


@pytest.mark.parametrize("stage,marker", [
    ("train", "model-freeze.json"),
    ("train", "final-evaluation-started.json"),
    ("evaluate_final", "final-evaluation-report.json"),
])
def test_closed_ensemble_runs_fail_before_loading_any_source(tmp_path, monkeypatch, stage, marker):
    pipeline = _pipeline()
    (tmp_path / marker).write_text("{}\n")

    def reject_data_access(args):
        pytest.fail("Closed runs must fail before accessing either development or reserved sources.")

    monkeypatch.setattr(pipeline, "verify_run_plan", reject_data_access)
    with pytest.raises(ValueError):
        getattr(pipeline, stage)(SimpleNamespace(output_dir=tmp_path))


def test_final_evaluation_rejects_changed_member_before_reserved_source_encoding(tmp_path, monkeypatch):
    pipeline = _pipeline()
    args = SimpleNamespace(output_dir=tmp_path, partition_plan=tmp_path / "partition.json")
    run_plan = {"runId": "unit-ensemble-integrity"}
    pipeline.write_json(tmp_path / "run-plan.json", run_plan)
    pipeline.write_json(args.partition_plan, {"unit": "partition"})
    checkpoint_path = tmp_path / "frozen-checkpoint.json"
    artifact = _unit_artifact()
    original_hash = pipeline.write_json(checkpoint_path, artifact)
    freeze = {
        "runId": run_plan["runId"],
        "runPlanSha256": pipeline.sha256_file(tmp_path / "run-plan.json"),
        "partitionPlanSha256": pipeline.sha256_file(args.partition_plan),
        "sourceSha256": {"trainer": "unit-frozen"},
        "files": {checkpoint_path.name: original_hash},
    }
    pipeline.write_json(tmp_path / "model-freeze.json", freeze)
    artifact["members"][0]["weights"]["b1"][0] += 1
    pipeline.write_json(checkpoint_path, artifact)
    monkeypatch.setattr(pipeline, "verify_run_plan", lambda args: (run_plan, {}, [], {}))
    monkeypatch.setattr(pipeline, "source_hashes", lambda: {"trainer": "unit-frozen"})

    def reject_reserved_encoding(rows):
        pytest.fail("Corrupted member weights must fail before reserved-source encoding.")

    monkeypatch.setattr(pipeline, "graph_pairs", reject_reserved_encoding)
    with pytest.raises(ValueError, match="[Ff]rozen artifact changed"):
        pipeline.evaluate_final(args)
    assert not (tmp_path / "final-evaluation-started.json").exists()


def _saved_artifacts():
    pipeline = _pipeline()
    directory = pipeline.DEFAULT_OUTPUT
    names = (
        "run-plan.json", "model-freeze.json", "frozen-checkpoint.json", "frozen-no-message-checkpoint.json",
        "cv-training-report.json", "final-evaluation-report.json", "deployment-manifest.json",
    )
    return pipeline, directory, {name: json.loads((directory / name).read_text()) for name in names}


def test_saved_deployment_preserves_frozen_five_members_and_excludes_reserved_tasks():
    pipeline, directory, artifacts = _saved_artifacts()
    run = artifacts["run-plan.json"]
    freeze = artifacts["model-freeze.json"]
    final = artifacts["final-evaluation-report.json"]
    deployment = artifacts["deployment-manifest.json"]
    checkpoint = artifacts["frozen-checkpoint.json"]
    no_message = artifacts["frozen-no-message-checkpoint.json"]
    paired_gnn.load_model.cache_clear()
    model = paired_gnn.load_model(pipeline.DEFAULT_MODEL)
    partition_path = ROOT / "evaluation/paired-code/cv-partition-plan.json"
    partition = json.loads(partition_path.read_text())
    reserved = set(partition["finalHoldoutTaskIds"])
    assert len(reserved) == 23
    assert len(partition["developmentTaskIds"]) == 120
    assert not reserved & set(partition["developmentTaskIds"])
    assert model["members"] == checkpoint["members"]
    assert "weights" not in model
    assert deployment["membersChangedAfterFreeze"] is False
    assert deployment["fullDevelopmentRefit"] is False
    assert freeze["fullDevelopmentRefit"] is False
    assert final["fullDevelopmentRefit"] is False
    assert freeze["finalHoldoutLearnedEncodingOrScoringPerformed"] is False
    assert pipeline.sha256_file(pipeline.DEFAULT_MODEL) == deployment["modelSha256"] == model["_artifactSha256"]
    assert pipeline.sha256_file(partition_path) == run["partitionPlanSha256"] == freeze["partitionPlanSha256"]
    assert pipeline.sha256_file(directory / "run-plan.json") == freeze["runPlanSha256"] == final["runPlanSha256"]
    for name, digest in freeze["files"].items():
        assert pipeline.sha256_file(directory / name) == digest
    assert pipeline.sha256_file(directory / "model-freeze.json") == final["freezeSha256"] == model["provenance"]["freezeSha256"]
    final_hash = pipeline.sha256_file(directory / "final-evaluation-report.json")
    assert final_hash == deployment["finalEvaluationReportSha256"] == model["provenance"]["finalEvaluationReportSha256"]
    assert deployment["frozenCheckpointSha256"] == freeze["files"]["frozen-checkpoint.json"] == final["checkpointSha256"]
    assert run["sourceSha256"] == freeze["sourceSha256"]
    for relative, digest in run["sourceSha256"].items():
        assert pipeline.sha256_file(directory / "source-snapshot" / relative) == digest

    for artifact, hash_key in ((checkpoint, "gnnMembersSha256"), (no_message, "noMessageMembersSha256")):
        assert artifact["kind"] == "FOLD_ENSEMBLE"
        assert artifact["ensemble"] == {"aggregation": "MEAN_COSINE", "members": 5}
        assert artifact["training"]["fullDevelopmentRefit"] is False
        assert len(artifact["members"]) == 5
        digest = hashlib.sha256(pipeline.canonical_bytes(artifact["members"])).hexdigest()
        assert digest == freeze[hash_key]
        if hash_key == "gnnMembersSha256":
            assert digest == deployment["membersSha256"]
        for member, declared in zip(artifact["members"], partition["folds"]):
            assert member["fold"] == declared["fold"]
            assert member["trainingTaskIds"] == declared["trainTaskIds"]
            assert member["validationTaskIds"] == declared["validationTaskIds"]
            assert len(member["trainingTaskIds"]) == 96
            assert len(member["validationTaskIds"]) == 24
            assert not reserved & set(member["trainingTaskIds"] + member["validationTaskIds"])
            assert member["selectedEpoch"] == artifact["training"]["selectedEpoch"]
    assert model["evaluation"]["test"] == final["metrics"]
    assert model["evaluation"]["finalHoldout"]["previouslyExposed"] is True
    assert model["evaluation"]["finalHoldout"]["protocolChangedAfterExposure"] is True


def _assert_saved_result_metrics(result, identifiers, pipeline):
    assert result["candidateOrder"] == identifiers
    assert [query["taskId"] for query in result["queries"]] == identifiers
    ranks = []
    matrices = []
    for query in result["queries"]:
        candidates = query["rankedCandidates"]
        candidate_ids = [candidate["taskId"] for candidate in candidates]
        assert len(candidate_ids) == len(set(candidate_ids)) == len(identifiers)
        assert set(candidate_ids) == set(identifiers)
        assert query["correctCandidateTaskId"] == query["taskId"]
        assert query["rank"] == candidate_ids.index(query["taskId"]) + 1
        assert query["reciprocalRank"] == pytest.approx(1 / query["rank"])
        similarities = [candidate["similarity"] for candidate in candidates]
        assert all(np.isfinite(similarity) for similarity in similarities)
        assert similarities == sorted(similarities, reverse=True)
        assert query["correctCandidateSimilarity"] == candidates[query["rank"] - 1]["similarity"]
        scores = {candidate["taskId"]: candidate["similarity"] for candidate in candidates}
        matrices.append([scores[task] for task in identifiers])
        stable_order = np.argsort(-np.asarray(matrices[-1]), kind="stable")
        assert candidate_ids == [identifiers[index] for index in stable_order]
        ranks.append(query["rank"])
    expected_metrics = pipeline.rank_metrics(ranks, len(identifiers))
    assert result["metrics"] == pytest.approx(expected_metrics)
    return np.asarray(matrices)


def test_saved_final_scores_and_ranks_are_exact_means_without_another_reserved_evaluation():
    pipeline, _, artifacts = _saved_artifacts()
    report = artifacts["final-evaluation-report.json"]
    identifiers = report["candidateOrder"]
    assert len(identifiers) == report["queries"] == report["candidatesPerQuery"] == 23
    assert set(report["results"]) == {
        "gnn", "noMessagePassing", "previousV1Gnn", "previousV2Gnn", "nameMatching", "semanticHistogram",
    }
    matrices = {}
    for label, result in report["results"].items():
        matrices[label] = _assert_saved_result_metrics(result, identifiers, pipeline)
        assert report["metrics"][label] == pytest.approx(result["metrics"])
    for label in ("gnn", "noMessagePassing"):
        members = report["individualMemberResults"][label]
        assert [member["fold"] for member in members] == [1, 2, 3, 4, 5]
        selected_epoch = report["selectedEpoch"] if label == "gnn" else report["noMessageSelectedEpoch"]
        assert all(member["selectedEpoch"] == selected_epoch for member in members)
        member_matrices = [_assert_saved_result_metrics(member, identifiers, pipeline) for member in members]
        np.testing.assert_allclose(matrices[label], np.mean(member_matrices, axis=0), rtol=0, atol=1e-15)


def test_saved_out_of_fold_selection_uses_only_declared_development_queries():
    pipeline, _, artifacts = _saved_artifacts()
    report = artifacts["cv-training-report.json"]
    partition = json.loads((ROOT / "evaluation/paired-code/cv-partition-plan.json").read_text())
    reserved = set(partition["finalHoldoutTaskIds"])
    assert report["fullDevelopmentRefit"] is False
    assert report["retainedCheckpoints"] == {"gnn": 5, "noMessagePassing": 5}
    assert report["finalHoldoutTasksNeverLearnedEncodedOrScoredAtThisStage"] == 23
    for label, folds in report["folds"].items():
        assert len(folds) == 5
        all_validation = []
        ranks = []
        selected_epoch = report["selection"][label]["selectedEpoch"]
        for fold, declared in zip(folds, partition["folds"]):
            assert fold["trainTaskIds"] == declared["trainTaskIds"]
            assert fold["candidateOrder"] == declared["validationTaskIds"]
            assert not reserved & set(fold["trainTaskIds"] + fold["candidateOrder"])
            queries = fold["selectedCheckpointPerQuery"]
            assert [query["taskId"] for query in queries] == declared["validationTaskIds"]
            selected = next(record for record in fold["history"] if record["epoch"] == selected_epoch)
            assert [query["rank"] for query in queries] == selected["ranks"]
            ranks.extend(selected["ranks"])
            all_validation.extend(fold["candidateOrder"])
        assert len(all_validation) == len(set(all_validation)) == 120
        assert set(all_validation) == set(partition["developmentTaskIds"])
        reconstructed = pipeline.select_epoch([fold["history"] for fold in folds])
        assert reconstructed == report["selection"][label]
        assert reconstructed["pooledMetrics"] == pytest.approx(pipeline.rank_metrics(ranks, 24))
