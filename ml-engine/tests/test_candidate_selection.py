"""Toy-only checks for development-selected candidate ensembles.

No corpus source is encoded or fitted here. Completed experiment reports are
audited from their saved hashes, rankings and scores without model inference.
"""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ml_engine import candidate_retrieval, paired_gnn
from ml_engine.candidate_gnn import initialise_candidate
from ml_engine.code_graph import CodeGraph, FEATURE_NAMES, RELATIONS
from ml_engine.structural_cca import FEAT_DIM, FEATURE_VERSION


ROOT = Path(__file__).resolve().parents[1]


def _pipeline():
    return importlib.import_module("scripts.train_paired_candidates")


def _cca_state():
    # An explicit unit fixture, not parameters fitted to any corpus rows.
    view = {"mean": np.zeros(FEAT_DIM).tolist(), "scale": np.ones(FEAT_DIM).tolist(),
            "projection": np.eye(FEAT_DIM, 24).tolist()}
    return {"kind": "STRUCTURAL_CCA", "featureVersion": FEATURE_VERSION,
            "regularization": 0.1, "output": 24, "trainingRows": 96,
            "canonicalCorrelations": np.zeros(24).tolist(),
            "cobol": copy.deepcopy(view), "java": copy.deepcopy(view)}


def _state(candidate, seed=431):
    if candidate == "structural_cca":
        return _cca_state()
    params = paired_gnn.initialise(seed) if candidate == "baseline" else initialise_candidate(candidate, seed)
    return {"weights": {name: value.tolist() for name, value in params.items()}}


def _unit_artifact(candidate="baseline"):
    identifiers = [f"Unit/{index}" for index in range(120)]
    epoch = 1 if candidate == "structural_cca" else 10
    members = []
    for fold in range(5):
        validation = identifiers[fold * 24:(fold + 1) * 24]
        members.append({"fold": fold + 1, "selectedEpoch": epoch,
                        "trainingTaskIds": [task for task in identifiers if task not in validation],
                        "validationTaskIds": validation, "state": _state(candidate, 431 + fold)})
    return {"id": "unit-candidate-" + candidate, "kind": "SELECTED_FOLD_ENSEMBLE",
            "candidateId": candidate, "featureNames": list(FEATURE_NAMES), "relations": list(RELATIONS),
            "ensemble": {"aggregation": "MEAN_COSINE", "members": 5}, "members": members,
            "training": {"dataset": "Unit fixture only", "fullDevelopmentRefit": False,
                         "selectedEpoch": epoch},
            "thresholds": {"minimumSimilarity": 1.0, "minimumMargin": 2.0},
            "evaluation": {"status": "UNIT_TEST_ONLY"}, "limitations": ["Never an accuracy benchmark."]}


def _marker_graph(marker):
    x = np.zeros((3, len(FEATURE_NAMES)))
    x[0, 0], x[1, 1], x[2, 2] = marker, 1.0, 2.0
    edges = {relation: np.array([[0, 1], [1, 2]], dtype=int) for relation in RELATIONS}
    return CodeGraph(x, edges, {})


def _histories(records):
    return [[{"epoch": epoch, "ranks": list(ranks), "validationLoss": loss}
             for epoch, ranks, loss in records] for _ in range(5)]


@pytest.mark.parametrize("records,expected", [
    ([(1, [1] + [24] * 23, 5.), (10, [2] * 24, .01)], 1),  # Top-1 beats MRR/loss.
    ([(1, [1] + [24] * 23, .01), (10, [1] + [2] * 23, 5.)], 10),
    ([(1, [2] * 24, 3.), (10, [2] * 24, 2.)], 10),
    ([(1, [2] * 24, 2.), (10, [2] * 24, 2.)], 1),
])
def test_checkpoint_selection_uses_top1_then_mrr_loss_and_earliest_epoch(records, expected):
    pipeline = _pipeline()
    result = pipeline.select_checkpoint(_histories(records))
    assert result["selectedEpoch"] == expected
    selected = next(record for record in records if record[0] == expected)
    assert result["pooledMetrics"] == pipeline.rank_metrics(selected[1] * 5, 24)


@pytest.mark.parametrize("change", ["four_folds", "empty_schedule", "different_schedule"])
def test_checkpoint_selection_rejects_incomplete_fold_evidence(change):
    histories = _histories([(1, [1] * 24, 1.)])
    if change == "four_folds":
        histories.pop()
    elif change == "empty_schedule":
        histories = [[] for _ in range(5)]
    else:
        histories[-1][0]["epoch"] = 2
    with pytest.raises(ValueError, match="consistent"):
        _pipeline().select_checkpoint(histories)


def test_candidate_selection_uses_top1_then_mrr_then_predeclared_order():
    pipeline = _pipeline()
    selections = {name: {"pooledMetrics": {"top1": .4, "mrr": .5}}
                  for name in pipeline.ORDER}
    assert pipeline.select_winner(selections) == pipeline.ORDER[0]
    selections["count_readout"]["pooledMetrics"]["mrr"] = .6
    assert pipeline.select_winner(selections) == "count_readout"
    selections["language_heads"]["pooledMetrics"] = {"top1": .5, "mrr": .01}
    assert pipeline.select_winner(selections) == "language_heads"
    del selections["baseline"]
    with pytest.raises(ValueError, match="Every declared candidate"):
        pipeline.select_winner(selections)


@pytest.mark.parametrize("candidate", candidate_retrieval.CANDIDATES)
def test_runtime_ensemble_dot_product_equals_mean_of_five_member_cosines(candidate, tmp_path):
    artifact = _unit_artifact(candidate)
    path = tmp_path / "model.json"
    path.write_text(json.dumps(artifact))
    paired_gnn.load_model.cache_clear()
    model = paired_gnn.load_model(path)
    cobol, java = _marker_graph(1.), _marker_graph(2.)
    before = json.dumps(model["members"], sort_keys=True)
    individual = [float(candidate_retrieval.member_embedding(cobol, member, candidate, "cobol") @
                        candidate_retrieval.member_embedding(java, member, candidate, "java"))
                  for member in model["members"]]
    combined = (paired_gnn.encode_graph(cobol, model, "cobol") @
                paired_gnn.encode_graph(java, model, "java"))
    assert combined == pytest.approx(float(np.mean(individual)), abs=1e-12)
    assert paired_gnn.encode_graph(cobol, model, "cobol").shape == (120,)
    assert before == json.dumps(model["members"], sort_keys=True)


@pytest.mark.parametrize("candidate", ["language_heads", "structural_cca"])
def test_two_view_models_require_explicit_valid_language(candidate):
    model = _unit_artifact(candidate)
    for language in (None, "", "python"):
        with pytest.raises(ValueError, match="language"):
            candidate_retrieval.encode_candidate(_marker_graph(1.), model, language)


def test_separate_language_heads_are_selected_by_the_explicit_language():
    model = _unit_artifact("language_heads")
    for member in model["members"]:
        member["state"]["weights"]["readout_java"] = (
            -np.asarray(member["state"]["weights"]["readout_cobol"])).tolist()
    query = candidate_retrieval.encode_candidate(_marker_graph(1.), model, "cobol")
    candidate = candidate_retrieval.encode_candidate(_marker_graph(1.), model, "java")
    np.testing.assert_allclose(query, -candidate, atol=1e-12)
    assert query @ candidate == pytest.approx(-1.)


def test_cca_uses_the_explicit_language_specific_preprocessing_and_projection():
    model = _unit_artifact("structural_cca")
    for member in model["members"]:
        member["state"]["java"]["projection"] = (
            -np.asarray(member["state"]["cobol"]["projection"])).tolist()
    query = candidate_retrieval.encode_candidate(_marker_graph(1.), model, "cobol")
    candidate = candidate_retrieval.encode_candidate(_marker_graph(1.), model, "java")
    np.testing.assert_allclose(query, -candidate, atol=1e-12)


@pytest.mark.parametrize("corruption", [
    "96_required", "24_required", "duplicate_fit", "fit_validation_overlap",
    "different_development", "repeated_validation", "wrong_fold", "mixed_epoch",
    "refit120", "root_weights", "unknown_candidate", "weight_nan", "wrong_heads",
])
def test_runtime_membership_and_model_schema_fail_closed(corruption):
    model = _unit_artifact("language_heads")
    if corruption == "96_required":
        model["members"][0]["trainingTaskIds"].pop()
    elif corruption == "24_required":
        model["members"][0]["validationTaskIds"].pop()
    elif corruption == "duplicate_fit":
        model["members"][0]["trainingTaskIds"][1] = model["members"][0]["trainingTaskIds"][0]
    elif corruption == "fit_validation_overlap":
        model["members"][0]["trainingTaskIds"][0] = model["members"][0]["validationTaskIds"][0]
    elif corruption == "different_development":
        model["members"][1]["trainingTaskIds"][0] = "Reserved/1"
    elif corruption == "repeated_validation":
        for field in ("trainingTaskIds", "validationTaskIds"):
            model["members"][1][field] = model["members"][0][field][:]
    elif corruption == "wrong_fold":
        model["members"][0]["fold"] = 2
    elif corruption == "mixed_epoch":
        model["members"][0]["selectedEpoch"] = 20
    elif corruption == "refit120":
        model["training"]["fullDevelopmentRefit"] = True
    elif corruption == "root_weights":
        model["weights"] = {}
    elif corruption == "unknown_candidate":
        model["candidateId"] = "unregistered-search-candidate"
    elif corruption == "weight_nan":
        model["members"][0]["state"]["weights"]["b1"][0] = float("nan")
    elif corruption == "wrong_heads":
        del model["members"][0]["state"]["weights"]["readout_java"]
    with pytest.raises(ValueError):
        candidate_retrieval.validate_candidate_model(model)


@pytest.mark.parametrize("corruption", ["trainingRows", "epoch", "scale", "projection"])
def test_cca_runtime_rejects_wrong_fit_rows_epoch_or_preprocessing(corruption):
    model = _unit_artifact("structural_cca")
    if corruption == "trainingRows":
        model["members"][0]["state"]["trainingRows"] = 120
    elif corruption == "epoch":
        model["training"]["selectedEpoch"] = 2
        for member in model["members"]:
            member["selectedEpoch"] = 2
    elif corruption == "scale":
        model["members"][0]["state"]["java"]["scale"][0] = 0.
    else:
        model["members"][0]["state"]["java"]["projection"] = [[0.]]
    with pytest.raises(ValueError):
        candidate_retrieval.validate_candidate_model(model)


def _unit_training_setup(tmp_path, monkeypatch):
    pipeline = _pipeline()
    model = _unit_artifact()
    development = [f"Unit/{index}" for index in range(120)]
    reserved = [f"HOLDOUT/{index}" for index in range(23)]
    partition = {"developmentTaskIds": development, "finalHoldoutTaskIds": reserved,
                 "folds": [{"fold": member["fold"], "trainTaskIds": member["trainingTaskIds"],
                            "validationTaskIds": member["validationTaskIds"]}
                           for member in model["members"]]}
    args = SimpleNamespace(output_dir=tmp_path, partition_plan=tmp_path / "partition.json",
                           seed=431, epochs=2, model_output=tmp_path / "selected.json")
    pipeline.write_json(args.partition_plan, partition)
    plan = {"runId": "unit-candidate-run", "partitionPlanSha256": pipeline.sha256_file(args.partition_plan),
            "configuration": {"seed": 431, "selection": "unit development-only OOF"}}
    pipeline.write_json(tmp_path / "run-plan.json", plan)
    rows = [{"task_id": identifier} for identifier in development + reserved]
    manifest = {"sha256": "unit-only-not-corpus"}
    monkeypatch.setattr(pipeline, "verify_plan", lambda args: (plan, partition, rows, manifest))
    monkeypatch.setattr(pipeline, "source_hashes", lambda: {"unit-source": "fixed"})
    return pipeline, args, plan, partition, rows, manifest


def test_train_graphs_only120_development_rows_and_fits_twenty_neural_and_five_cca96s(tmp_path, monkeypatch):
    pipeline, args, plan, partition, _, _ = _unit_training_setup(tmp_path, monkeypatch)
    graphed, neural_fits, cca_fits, preprocessing = [], [], [], []

    def fake_graphs(rows):
        identifiers = [row["task_id"] for row in rows]
        assert identifiers == partition["developmentTaskIds"]
        assert not set(identifiers) & set(partition["finalHoldoutTaskIds"])
        graphed.append(identifiers)
        return ([f"C:{index}" for index in range(120)], [f"J:{index}" for index in range(120)])

    def fake_features(graph):
        assert "HOLDOUT" not in graph
        # Fixed extraction is not a fitted preprocessing transformation.
        return np.array([float(graph.split(":")[1]), float(graph.startswith("J"))])

    def fake_fit_neural(graphs, fitting, validation, candidate, seed, epochs):
        assert candidate != "structural_cca"
        assert len(fitting) == 96 and len(validation) == 24
        assert not set(fitting) & set(validation)
        assert sorted(fitting + validation) == list(range(120))
        neural_fits.append((candidate, fitting[:], validation[:]))
        history = [{"epoch": epoch, "ranks": [1] * 24, "validationLoss": 1.} for epoch in (1, 2)]
        state = _state(candidate)
        weights = {name: np.asarray(value) for name, value in state["weights"].items()}
        return history, {epoch: {"weights": {name: value.copy() for name, value in weights.items()}}
                         for epoch in (1, 2)}

    def fake_fit_cca(cobol, java, regularization, output):
        assert cobol.shape == java.shape == (96, 2)
        np.testing.assert_array_equal(cobol[:, 0], java[:, 0])
        assert regularization == .1 and output == 24
        cca_fits.append(cobol[:, 0].astype(int).tolist())
        return _cca_state()

    def fake_encode_cca(features, state, language):
        assert len(features) == 24  # Fitted state is only applied to its validation rows.
        assert language in ("cobol", "java") and state["trainingRows"] == 96
        preprocessing.append((language, features[:, 0].astype(int).tolist()))
        return np.eye(24)

    def prohibit_full_fit(*args, **kwargs):
        pytest.fail("No120-pair optimizer fit or final full-development refit is permitted.")

    monkeypatch.setattr(pipeline, "graph_pairs", fake_graphs)
    monkeypatch.setattr(pipeline, "graph_features", fake_features)
    monkeypatch.setattr(pipeline, "fit_neural", fake_fit_neural)
    monkeypatch.setattr(pipeline, "fit_cca", fake_fit_cca)
    monkeypatch.setattr(pipeline, "encode_cca", fake_encode_cca)
    monkeypatch.setattr(importlib.import_module("scripts.train_paired_gnn_cv"), "fit_full", prohibit_full_fit)
    result = pipeline.train(args)
    assert result["stage"] == "FROZEN" and result["cvWinner"] == "baseline"
    assert graphed == [partition["developmentTaskIds"]]
    assert len(neural_fits) == 20 and len(cca_fits) == 5 and len(preprocessing) == 10
    for candidate in set(pipeline.ORDER) - {"structural_cca"}:
        fits = [(train, val) for name, train, val in neural_fits if name == candidate]
        assert len(fits) == 5
        assert sorted(index for _, validation in fits for index in validation) == list(range(120))
    for indices, fold in zip(cca_fits, partition["folds"]):
        assert [partition["developmentTaskIds"][index] for index in indices] == fold["trainTaskIds"]
    freeze = pipeline.read_json(tmp_path / "model-freeze.json")
    assert freeze["cvWinner"] == "baseline"
    assert freeze["fullDevelopmentRefit"] is False
    assert freeze["finalLearnedEncodingOrScoringPerformed"] is False
    assert set(freeze["memberSha256"]) == set(pipeline.ORDER)
    for candidate in pipeline.ORDER:
        path = tmp_path / f"frozen-{candidate}.json"
        artifact = pipeline.read_json(path)
        assert pipeline.sha256_file(path) == freeze["files"][path.name]
        assert pipeline.sha256_bytes(pipeline.canonical_bytes(artifact["members"])) == freeze["memberSha256"][candidate]
        assert artifact["training"]["fullDevelopmentRefit"] is False
        for member, fold in zip(artifact["members"], partition["folds"]):
            assert member["trainingTaskIds"] == fold["trainTaskIds"]
            assert member["validationTaskIds"] == fold["validationTaskIds"]
            assert not set(member["trainingTaskIds"] + member["validationTaskIds"]) & set(partition["finalHoldoutTaskIds"])
    assert not (tmp_path / "final-evaluation-started.json").exists()


@pytest.mark.parametrize("stage,marker", [("train", "model-freeze.json"),
                                           ("evaluate_final", "final-evaluation-report.json")])
def test_completed_stages_cannot_overwrite_existing_evidence(tmp_path, monkeypatch, stage, marker):
    pipeline, args, *_ = _unit_training_setup(tmp_path, monkeypatch)
    (tmp_path / marker).write_text("{}")
    with pytest.raises(ValueError):
        getattr(pipeline, stage)(args)


@pytest.mark.parametrize("corruption", ["source", "plan", "partition", "refit", "file", "winner"])
def test_final_guards_reject_changed_evidence_before_any_holdout_graphing(tmp_path, monkeypatch, corruption):
    pipeline, args, plan, _, _, _ = _unit_training_setup(tmp_path, monkeypatch)
    selections = {name: {"pooledMetrics": {"top1": .5, "mrr": .6}} for name in pipeline.ORDER}
    cv = {"cvWinner": "baseline", "selections": selections}
    cv_path = tmp_path / "cv-training-report.json"
    cv_hash = pipeline.write_json(cv_path, cv)
    freeze = {"runId": plan["runId"], "sourceSha256": pipeline.source_hashes(),
              "runPlanSha256": pipeline.sha256_file(tmp_path / "run-plan.json"),
              "partitionPlanSha256": plan["partitionPlanSha256"], "fullDevelopmentRefit": False,
              "files": {cv_path.name: cv_hash}, "cvWinner": "baseline"}
    if corruption == "source":
        freeze["sourceSha256"] = {"changed": "source"}
    elif corruption == "plan":
        freeze["runPlanSha256"] = "changed"
    elif corruption == "partition":
        freeze["partitionPlanSha256"] = "changed"
    elif corruption == "refit":
        freeze["fullDevelopmentRefit"] = True
    elif corruption == "file":
        cv_path.write_text("{}")
    else:
        freeze["cvWinner"] = "count_readout"
    pipeline.write_json(tmp_path / "model-freeze.json", freeze)

    def reject_graphs(rows):
        pytest.fail("No reserved source may reach graph encoding after integrity failure.")

    monkeypatch.setattr(pipeline, "graph_pairs", reject_graphs)
    with pytest.raises(ValueError):
        pipeline.evaluate_final(args)
    assert not (tmp_path / "final-evaluation-started.json").exists()


def _saved_artifacts():
    pipeline = _pipeline()
    directory = pipeline.DEFAULT_OUTPUT
    if not (directory / "final-evaluation-report.json").exists():
        pytest.skip("The separately frozen, once-only candidate assessment has not completed.")
    names = ("run-plan.json", "model-freeze.json", "cv-training-report.json",
             "final-evaluation-report.json", "deployment-manifest.json")
    return pipeline, directory, {name: pipeline.read_json(directory / name) for name in names}


def test_saved_candidate_freeze_preserves_all_states_sources_and_excludes_reserved_tasks():
    pipeline, directory, artifacts = _saved_artifacts()
    plan, freeze = artifacts["run-plan.json"], artifacts["model-freeze.json"]
    partition_path = ROOT / "evaluation/paired-code/cv-partition-plan.json"
    partition = pipeline.read_json(partition_path)
    reserved = set(partition["finalHoldoutTaskIds"])
    assert len(reserved) == 23 and len(partition["developmentTaskIds"]) == 120
    assert not reserved & set(partition["developmentTaskIds"])
    assert plan["configuration"]["fullDevelopmentRefit"] is False
    assert freeze["fullDevelopmentRefit"] is False
    assert freeze["finalLearnedEncodingOrScoringPerformed"] is False
    assert pipeline.sha256_file(partition_path) == plan["partitionPlanSha256"] == freeze["partitionPlanSha256"]
    assert pipeline.sha256_file(directory / "run-plan.json") == freeze["runPlanSha256"]
    assert plan["sourceSha256"] == freeze["sourceSha256"]
    for relative, digest in plan["sourceSha256"].items():
        assert pipeline.sha256_file(directory / "source-snapshot" / relative) == digest
    for filename, digest in freeze["files"].items():
        assert pipeline.sha256_file(directory / filename) == digest
    assert set(freeze["memberSha256"]) == set(pipeline.ORDER)
    for candidate in pipeline.ORDER:
        artifact = pipeline.read_json(directory / f"frozen-{candidate}.json")
        candidate_retrieval.validate_candidate_model(artifact)
        assert artifact["candidateId"] == candidate
        assert artifact["training"]["fullDevelopmentRefit"] is False
        assert pipeline.sha256_bytes(pipeline.canonical_bytes(artifact["members"])) == freeze["memberSha256"][candidate]
        for member, fold in zip(artifact["members"], partition["folds"]):
            assert member["trainingTaskIds"] == fold["trainTaskIds"]
            assert member["validationTaskIds"] == fold["validationTaskIds"]
            assert not reserved & set(member["trainingTaskIds"] + member["validationTaskIds"])
            assert len(member["trainingTaskIds"]) == 96 and len(member["validationTaskIds"]) == 24
            if candidate == "structural_cca":
                assert member["state"]["trainingRows"] == 96


def test_saved_cv_checkpoint_and_winner_are_reproducible_using_only_development_ranks():
    pipeline, _, artifacts = _saved_artifacts()
    cv, freeze = artifacts["cv-training-report.json"], artifacts["model-freeze.json"]
    partition = pipeline.read_json(ROOT / "evaluation/paired-code/cv-partition-plan.json")
    reserved = set(partition["finalHoldoutTaskIds"])
    assert cv["fullDevelopmentRefit"] is False
    assert cv["finalLearnedEncodingOrScoringPerformed"] is False
    assert set(cv["folds"]) == set(pipeline.ORDER) == set(cv["selections"])
    for candidate, folds in cv["folds"].items():
        assert len(folds) == 5
        validation_ids = []
        for fold, declared in zip(folds, partition["folds"]):
            assert fold["trainTaskIds"] == declared["trainTaskIds"]
            assert fold["candidateOrder"] == declared["validationTaskIds"]
            assert not reserved & set(fold["trainTaskIds"] + fold["candidateOrder"])
            assert all(len(checkpoint["ranks"]) == 24 for checkpoint in fold["history"])
            validation_ids.extend(fold["candidateOrder"])
        assert len(validation_ids) == len(set(validation_ids)) == 120
        assert set(validation_ids) == set(partition["developmentTaskIds"])
        reconstructed = pipeline.select_checkpoint([fold["history"] for fold in folds])
        assert reconstructed == cv["selections"][candidate]
    assert pipeline.select_winner(cv["selections"]) == cv["cvWinner"] == freeze["cvWinner"]


def _saved_score_matrix(result, identifiers, pipeline):
    assert result["candidateOrder"] == identifiers
    assert [query["taskId"] for query in result["queries"]] == identifiers
    scores, ranks = [], []
    for query in result["queries"]:
        ranked = query["rankedCandidates"]
        ranked_ids = [candidate["taskId"] for candidate in ranked]
        assert len(ranked_ids) == len(set(ranked_ids)) == len(identifiers)
        assert set(ranked_ids) == set(identifiers)
        values = {candidate["taskId"]: candidate["similarity"] for candidate in ranked}
        row = np.array([values[identifier] for identifier in identifiers])
        assert np.all(np.isfinite(row))
        assert ranked_ids == [identifiers[index] for index in np.argsort(-row, kind="stable")]
        rank = ranked_ids.index(query["taskId"]) + 1
        assert rank == query["rank"]
        assert query["correctCandidateTaskId"] == query["taskId"]
        assert query["correctCandidateSimilarity"] == values[query["taskId"]]
        assert query["reciprocalRank"] == pytest.approx(1 / rank)
        ranks.append(rank)
        scores.append(row)
    assert result["metrics"] == pytest.approx(pipeline.rank_metrics(ranks, len(identifiers)))
    return np.stack(scores)


def test_saved_final_rankings_equal_mean_of_all_five_cached_members_without_new_inference():
    pipeline, _, artifacts = _saved_artifacts()
    report = artifacts["final-evaluation-report.json"]
    identifiers = report["candidateOrder"]
    partition = pipeline.read_json(ROOT / "evaluation/paired-code/cv-partition-plan.json")
    assert identifiers == partition["finalHoldoutTaskIds"]
    assert len(identifiers) == report["queries"] == report["candidatesPerQuery"] == 23
    assert report["fullDevelopmentRefit"] is False
    assert set(report["results"]) == set(pipeline.ORDER) | {"nameMatching", "semanticHistogram"}
    for candidate, result in report["results"].items():
        scores = _saved_score_matrix(result, identifiers, pipeline)
        assert report["metrics"][candidate] == result["metrics"]
        if candidate in pipeline.ORDER:
            members = report["individualMemberResults"][candidate]
            assert [member["fold"] for member in members] == [1, 2, 3, 4, 5]
            member_scores = [_saved_score_matrix(member, identifiers, pipeline) for member in members]
            np.testing.assert_allclose(scores, np.mean(member_scores, axis=0), rtol=0, atol=1e-15)


def test_saved_deployment_uses_the_frozen_cv_winner_and_unchanged_members():
    pipeline, directory, artifacts = _saved_artifacts()
    freeze, cv = artifacts["model-freeze.json"], artifacts["cv-training-report.json"]
    report, deployment = artifacts["final-evaluation-report.json"], artifacts["deployment-manifest.json"]
    paired_gnn.load_model.cache_clear()
    deployed = paired_gnn.load_model(pipeline.DEFAULT_MODEL)
    winner = pipeline.select_winner(cv["selections"])
    frozen = pipeline.read_json(directory / f"frozen-{winner}.json")
    assert winner == freeze["cvWinner"] == report["cvWinner"] == deployment["candidateId"] == deployed["candidateId"]
    assert deployed["members"] == frozen["members"]
    assert deployment["membersChangedAfterFreeze"] is False
    assert deployment["fullDevelopmentRefit"] is False
    assert deployment["memberSha256"] == freeze["memberSha256"][winner]
    assert deployment["modelSha256"] == pipeline.sha256_file(pipeline.DEFAULT_MODEL) == deployed["_artifactSha256"]
    freeze_hash = pipeline.sha256_file(directory / "model-freeze.json")
    report_hash = pipeline.sha256_file(directory / "final-evaluation-report.json")
    assert freeze_hash == report["freezeSha256"] == deployed["provenance"]["freezeSha256"]
    assert report_hash == deployment["finalEvaluationReportSha256"] == deployed["provenance"]["finalEvaluationReportSha256"]
    assert deployed["evaluation"]["finalHoldout"]["previouslyExposed"] is True
    assert deployed["evaluation"]["financialDomainValidated"] is False
    assert deployed["evaluation"]["test"] == report["metrics"]
