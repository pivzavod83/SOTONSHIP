"""Protocol integrity checks for grouped cross-validation and a frozen holdout.

The small source strings below exercise partitioning only. They are test inputs,
never training records or substitutes for the pinned paired-source benchmark.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
import numpy as np

from scripts.train_paired_gnn_cv import select_epoch
from scripts import train_paired_gnn_cv as cv_training
from ml_engine.cv_partition import build_partition_plan, validate_partition_plan
from ml_engine.paired_gnn import MODEL_PATH, load_model, model_metadata


ROOT = Path(__file__).resolve().parents[1]
CV_ARTIFACTS = ROOT / "evaluation/paired-code/cv-v2"


def _read_artifact(name):
    return json.loads((CV_ARTIFACTS / name).read_text())


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metrics_from_saved_ranks(ranks, gallery_size):
    """Recompute report arithmetic only; never run the learned encoder again."""
    assert ranks and all(isinstance(rank, int) and 1 <= rank <= gallery_size for rank in ranks)
    count = len(ranks)
    return {
        "queries": count,
        "candidatesPerQuery": gallery_size,
        "top1": sum(rank == 1 for rank in ranks) / count,
        "top3": sum(rank <= 3 for rank in ranks) / count,
        "top5": sum(rank <= 5 for rank in ranks) / count,
        "mrr": sum(1 / rank for rank in ranks) / count,
    }


def test_historical_v2_model_matches_frozen_weights_and_complete_artifact_hash_chain():
    historical_path = ROOT / 'ml_engine/models/paired_program_gnn_v2_cv.json'
    model = load_model(historical_path)
    metadata = model_metadata(model)
    deployment = _read_artifact("deployment-manifest.json")
    freeze = _read_artifact("model-freeze.json")
    checkpoint = _read_artifact("frozen-checkpoint.json")
    no_message = _read_artifact("frozen-no-message-checkpoint.json")
    cv_report = _read_artifact("cv-training-report.json")
    final_report = _read_artifact("final-evaluation-report.json")
    run_plan = _read_artifact("run-plan.json")

    assert metadata["id"] == deployment["modelId"] == final_report["modelId"]
    assert metadata["sha256"] == deployment["modelSha256"] == _file_hash(historical_path)
    assert model["weights"] == checkpoint["weights"]
    assert deployment["weightsChangedAfterFreeze"] is False
    weights_hash = hashlib.sha256(cv_training.canonical_bytes(model["weights"])).hexdigest()
    assert weights_hash == deployment["weightsSha256"] == freeze["gnnWeightsSha256"]
    assert hashlib.sha256(cv_training.canonical_bytes(no_message["weights"])).hexdigest() == freeze["noMessageWeightsSha256"]
    for name, digest in freeze["files"].items():
        assert _file_hash(CV_ARTIFACTS / name) == digest
    assert freeze["files"]["frozen-checkpoint.json"] == deployment["frozenCheckpointSha256"] == final_report["checkpointSha256"]
    assert freeze["files"]["frozen-no-message-checkpoint.json"] == final_report["noMessageCheckpointSha256"]
    final_hash = _file_hash(CV_ARTIFACTS / "final-evaluation-report.json")
    assert final_hash == deployment["finalEvaluationReportSha256"] == model["provenance"]["finalEvaluationReportSha256"]
    assert _file_hash(CV_ARTIFACTS / "model-freeze.json") == final_report["freezeSha256"] == model["provenance"]["freezeSha256"]
    assert _file_hash(CV_ARTIFACTS / "run-plan.json") == freeze["runPlanSha256"] == cv_report["runPlanSha256"] == final_report["runPlanSha256"]
    partition_hash = _file_hash(ROOT / "evaluation/paired-code/cv-partition-plan.json")
    assert partition_hash == run_plan["partitionPlanSha256"] == freeze["partitionPlanSha256"] == final_report["partitionPlanSha256"]
    assert len({artifact["runId"] for artifact in (deployment, freeze, cv_report, final_report, run_plan)}) == 1
    assert freeze["freezeId"] == final_report["freezeId"] == model["provenance"]["freezeId"]
    for relative_path, digest in freeze["sourceSha256"].items():
        assert _file_hash(CV_ARTIFACTS / 'source-snapshot' / relative_path) == digest

    assert model["training"]["splitCounts"] == no_message["training"]["splitCounts"] == {"development": 120, "finalHoldout": 23}
    assert model["training"]["crossValidation"]["folds"] == 5
    assert model["training"]["crossValidation"]["trainPerFold"] == 96
    assert model["training"]["crossValidation"]["validationPerFold"] == 24
    assert model["training"]["selectedEpoch"] == freeze["selectedEpoch"] == final_report["selectedEpoch"]
    assert no_message["training"]["selectedEpoch"] == freeze["noMessageSelectedEpoch"] == final_report["noMessageSelectedEpoch"]
    for artifact in (checkpoint, no_message, freeze, cv_report, final_report):
        assert artifact["thresholds"] == model["thresholds"]
    assert model["thresholds"]["calibration"]["enabled"] is False
    assert model["evaluation"]["test"] == final_report["metrics"]
    assert model["evaluation"]["finalHoldout"]["previouslyExposed"] is True
    assert model["evaluation"]["financialDomainValidated"] is False


def test_saved_final_and_cv_metrics_follow_per_query_ranks_without_new_holdout_scoring():
    plan = json.loads((ROOT / "evaluation/paired-code/cv-partition-plan.json").read_text())
    final_report = _read_artifact("final-evaluation-report.json")
    cv_report = _read_artifact("cv-training-report.json")
    freeze = _read_artifact("model-freeze.json")
    gallery = plan["finalHoldoutTaskIds"]
    assert final_report["queries"] == final_report["candidatesPerQuery"] == len(gallery) == 23
    assert final_report["candidateOrder"] == gallery
    assert set(final_report["results"]) == {"gnn", "noMessagePassing", "previousV1Gnn", "nameMatching", "semanticHistogram"}
    for label, result in final_report["results"].items():
        assert result["candidateOrder"] == gallery
        assert [query["taskId"] for query in result["queries"]] == gallery
        ranks = []
        for query in result["queries"]:
            assert query["correctCandidateTaskId"] == query["taskId"]
            candidates = query["rankedCandidates"]
            identifiers = [candidate["taskId"] for candidate in candidates]
            assert len(identifiers) == len(set(identifiers)) == 23
            assert set(identifiers) == set(gallery)
            assert query["rank"] == identifiers.index(query["taskId"]) + 1
            assert query["reciprocalRank"] == pytest.approx(1 / query["rank"])
            similarities = [candidate["similarity"] for candidate in candidates]
            assert all(np.isfinite(similarity) for similarity in similarities)
            assert similarities == sorted(similarities, reverse=True)
            assert query["correctCandidateSimilarity"] == candidates[query["rank"] - 1]["similarity"]
            ranks.append(query["rank"])
        expected = _metrics_from_saved_ranks(ranks, 23)
        assert result["metrics"] == pytest.approx(expected)
        assert final_report["metrics"][label] == pytest.approx(expected)

    for label, folds in cv_report["folds"].items():
        assert len(folds) == 5
        selected_epoch = cv_report["selection"][label]["selectedEpoch"]
        ranks = []
        for fold, declared in zip(folds, plan["folds"]):
            assert fold["trainTaskIds"] == declared["trainTaskIds"]
            assert fold["candidateOrder"] == declared["validationTaskIds"]
            queries = fold["selectedCheckpointPerQuery"]
            assert [query["taskId"] for query in queries] == declared["validationTaskIds"]
            selected = next(record for record in fold["history"] if record["epoch"] == selected_epoch)
            assert [query["rank"] for query in queries] == selected["ranks"]
            ranks.extend(selected["ranks"])
        assert cv_report["selection"][label]["pooledMetrics"] == pytest.approx(_metrics_from_saved_ranks(ranks, 24))
        reconstructed = select_epoch([fold["history"] for fold in folds])
        assert reconstructed["selectedEpoch"] == selected_epoch
    assert cv_report["developmentTasks"] == 120
    assert cv_report["finalHoldoutTasksNeverLearnedEncodedOrScoredAtThisStage"] == 23
    assert freeze["finalHoldoutLearnedEncodingOrScoringPerformed"] is False
    exposure = final_report["priorExposure"]
    assert exposure["previouslyEvaluatedFinalHoldoutTasks"] == 23
    assert exposure["priorMembershipCounts"] == {"train": 0, "validation": 0, "test": 23}
    assert set(exposure["finalHoldoutTaskPriorMembership"]) == set(gallery)
    assert set(exposure["finalHoldoutTaskPriorMembership"].values()) == {"test"}


@pytest.fixture(scope="module")
def toy_partition():
    rows = []
    for index in range(143):
        expression = " + ".join(str(index * 10 + offset) for offset in range(1, 9))
        rows.append({
            "task_id": f"Task/{index}",
            "Java_canonical_solution": f"class Example {{ int compute() {{ return {expression}; }} }}",
            "COBOL_canonical_solution": (
                "IDENTIFICATION DIVISION.\nPROGRAM-ID. EXAMPLE.\nDATA DIVISION.\n"
                "WORKING-STORAGE SECTION.\n01 ANSWER PIC 9(8).\n"
                f"PROCEDURE DIVISION.\nCOMPUTE ANSWER = {expression}.\nGOBACK."
            ),
        })
    # One known connected component must stay together in every partition.
    for field in ("Java_canonical_solution", "COBOL_canonical_solution"):
        rows[1][field] = rows[0][field]
    ids = [row["task_id"] for row in rows]
    prior = {"splits": {"train": ids[:85], "validation": ids[85:114], "test": ids[114:]}}
    plan = build_partition_plan(rows, prior, seed=431)
    return rows, prior, plan


def test_partition_assignment_is_deterministic_source_bound_and_preserves_groups(toy_partition):
    rows, prior, plan = toy_partition
    repeated = build_partition_plan(list(reversed(rows)), prior, seed=431)
    assert repeated == plan
    assert set(plan["finalHoldoutTaskIds"]) <= set(prior["splits"]["test"])
    assert ["Task/0", "Task/1"] in plan["graphPartitioning"]["groups"]
    assert validate_partition_plan(plan, rows) is None


@pytest.mark.parametrize("corruption", ["duplicate_holdout", "holdout_in_training", "repeated_validation", "changed_graph_groups"])
def test_partition_validator_rejects_split_or_group_tampering(toy_partition, corruption):
    rows, _, original = toy_partition
    plan = copy.deepcopy(original)
    if corruption == "duplicate_holdout":
        plan["finalHoldoutTaskIds"][1] = plan["finalHoldoutTaskIds"][0]
    elif corruption == "holdout_in_training":
        plan["folds"][0]["trainTaskIds"][0] = plan["finalHoldoutTaskIds"][0]
    elif corruption == "repeated_validation":
        plan["folds"][1]["validationTaskIds"] = plan["folds"][0]["validationTaskIds"][:]
        plan["folds"][1]["trainTaskIds"] = plan["folds"][0]["trainTaskIds"][:]
    elif corruption == "changed_graph_groups":
        plan["graphPartitioning"]["groups"] = [[task] for task in plan["developmentTaskIds"] + plan["finalHoldoutTaskIds"]]
    with pytest.raises(ValueError):
        validate_partition_plan(plan, rows)


def test_partition_validator_rejects_source_changes_after_freeze(toy_partition):
    rows, _, plan = toy_partition
    changed = copy.deepcopy(rows)
    changed[4]["Java_canonical_solution"] += "\n// source edit after freezing"
    with pytest.raises(ValueError, match="source rows have changed"):
        validate_partition_plan(plan, changed)


def test_partition_validator_rejects_component_cut_even_with_exact_fold_sizes(toy_partition):
    rows, _, original = toy_partition
    plan = copy.deepcopy(original)
    containing = next(fold for fold in plan["folds"] if "Task/0" in fold["validationTaskIds"])
    other = next(fold for fold in plan["folds"] if fold is not containing)
    replacement = other["validationTaskIds"][0]
    containing["validationTaskIds"].remove("Task/1")
    containing["validationTaskIds"].append(replacement)
    other["validationTaskIds"].remove(replacement)
    other["validationTaskIds"].append("Task/1")
    for fold in plan["folds"]:
        fold["trainTaskIds"] = sorted(set(plan["developmentTaskIds"]) - set(fold["validationTaskIds"]))
    with pytest.raises(ValueError, match="graph component"):
        validate_partition_plan(plan, rows)


def test_committed_cv_plan_reserves_23_tasks_and_covers_120_once_in_validation():
    plan = json.loads((ROOT / "evaluation/paired-code/cv-partition-plan.json").read_text())
    development = set(plan["developmentTaskIds"])
    holdout = set(plan["finalHoldoutTaskIds"])
    assert len(plan["developmentTaskIds"]) == len(development) == 120
    assert len(plan["finalHoldoutTaskIds"]) == len(holdout) == 23
    assert not development & holdout
    assert len(development | holdout) == 143
    assert len(plan["folds"]) == 5

    validation_appearances = Counter()
    groups = [set(group) for group in plan["graphPartitioning"]["groups"]]
    assert set().union(*groups) == development | holdout
    assert sum(map(len, groups)) == 143
    for group in groups:
        assert group <= development or group <= holdout

    for fold in plan["folds"]:
        train = set(fold["trainTaskIds"])
        validation = set(fold["validationTaskIds"])
        assert len(fold["trainTaskIds"]) == len(train) == 96
        assert len(fold["validationTaskIds"]) == len(validation) == 24
        assert not train & validation
        assert train | validation == development
        assert not (train | validation) & holdout
        validation_appearances.update(validation)
        for group in groups:
            assert not (group & train and group & validation)
    assert validation_appearances == Counter({task: 1 for task in development})


def _checkpoint(epoch, ranks, loss=0.5):
    return {
        "epoch": epoch,
        "trainLoss": 1.0,
        "validationLoss": loss,
        "ranks": ranks,
    }


def test_cv_epoch_selection_pools_queries_instead_of_unweighted_fold_means():
    # The larger validation fold must contribute more queries to the decision.
    histories = [
        [_checkpoint(1, [1, 1], 1.0), _checkpoint(10, [2, 2], 1.0)],
        [_checkpoint(1, [2, 2, 2], 0.5), _checkpoint(10, [1, 1, 1], 0.5)],
    ]
    result = select_epoch(histories)
    assert result["selectedEpoch"] == 10
    assert result["pooledMetrics"]["queries"] == 5
    assert result["pooledMetrics"]["mrr"] == pytest.approx(0.8)
    assert result["pooledMetrics"]["top1"] == pytest.approx(0.6)
    assert result["weightedValidationLoss"] == pytest.approx(0.7)
    assert result["candidatesPerQueryByFold"] == [2, 3]


def test_cv_selection_uses_validation_loss_then_earliest_epoch_to_break_ties():
    histories = [
        [_checkpoint(1, [1, 2], 0.9), _checkpoint(10, [1, 2], 0.4), _checkpoint(20, [1, 2], 0.4)],
        [_checkpoint(1, [2, 1], 0.9), _checkpoint(10, [2, 1], 0.4), _checkpoint(20, [2, 1], 0.4)],
    ]
    assert select_epoch(histories)["selectedEpoch"] == 10


@pytest.mark.parametrize(
    "histories",
    [
        [],
        [[]],
        [[_checkpoint(1, [1, 2])], [_checkpoint(10, [1, 2])]],
        [[_checkpoint(1, [1, 2]), _checkpoint(1, [1, 2])]],
        [[_checkpoint(0, [1, 2])]],
        [[_checkpoint(1, [0, 1])]],
        [[_checkpoint(1, [1, 3])]],
        [[_checkpoint(1, [])]],
    ],
)
def test_cv_selection_rejects_invalid_or_incomparable_histories(histories):
    with pytest.raises(ValueError):
        select_epoch(histories)


def test_fold_and_final_refit_use_fresh_parameters_optimizer_and_explicit_sources(monkeypatch):
    # Mock the numerical kernels: this is a protocol test, not another training run.
    graphs = (["C0", "C1", "C2", "C3", "HOLDOUT_C"],
              ["J0", "J1", "J2", "J3", "HOLDOUT_J"])
    batches = []
    parameter_objects = []
    optimizer_objects = []

    def fake_batch(selected, message_passing):
        assert not any("HOLDOUT" in graph for graph in selected)
        batches.append((selected[:], message_passing))
        return selected

    def fake_initialise(seed):
        parameters = {"weight": np.array([float(seed)])}
        parameter_objects.append(parameters)
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
            optimizer_objects.append((first, second))
        first["weight"] += 1
        second["weight"] += 2
        parameters["weight"] += 1

    monkeypatch.setattr(cv_training, "batch_graphs", fake_batch)
    monkeypatch.setattr(cv_training, "initialise", fake_initialise)
    monkeypatch.setattr(cv_training, "forward", fake_forward)
    monkeypatch.setattr(cv_training, "backward", fake_backward)
    monkeypatch.setattr(cv_training, "adam_step", fake_adam)

    first = cv_training.fit_fold(graphs, [0, 1], [2, 3], seed=431, epochs=2, message_passing=True)
    second = cv_training.fit_fold(graphs, [2, 3], [0, 1], seed=431, epochs=2, message_passing=True)
    final = cv_training.fit_full(graphs, [0, 1, 2, 3], seed=431, epochs=2, message_passing=True)

    assert [row["epoch"] for row in first] == [1, 2]
    assert first == second
    assert len(parameter_objects) == len(optimizer_objects) == 3
    assert len({id(parameters["weight"]) for parameters in parameter_objects}) == 3
    assert len({id(first_state["weight"]) for first_state, _ in optimizer_objects}) == 3
    assert batches[-2:] == [(["C0", "C1", "C2", "C3"], True), (["J0", "J1", "J2", "J3"], True)]
    np.testing.assert_array_equal(final["weight"], [433.0])


def test_fitting_refuses_overlap_between_fold_training_and_validation():
    with pytest.raises(ValueError, match="disjoint"):
        cv_training.fit_fold(([], []), [0, 1], [1, 2], seed=431, epochs=1, message_passing=True)


@pytest.mark.parametrize("stage,marker", [
    ("train", "model-freeze.json"),
    ("train", "final-evaluation-started.json"),
    ("evaluate_final", "final-evaluation-report.json"),
])
def test_frozen_or_completed_run_cannot_be_retrained_or_silently_reevaluated(tmp_path, monkeypatch, stage, marker):
    (tmp_path / marker).write_text("{}\n")

    def refuse_data_access(args):
        pytest.fail("A closed run must be rejected before loading any sources.")

    monkeypatch.setattr(cv_training, "verify_run_plan", refuse_data_access)
    with pytest.raises(ValueError):
        getattr(cv_training, stage)(SimpleNamespace(output_dir=tmp_path))


def test_final_evaluation_rejects_modified_checkpoint_before_holdout_encoding(tmp_path, monkeypatch):
    args = SimpleNamespace(output_dir=tmp_path, partition_plan=tmp_path / "partition.json")
    run_plan = {"runId": "integrity-test"}
    cv_training.write_json(tmp_path / "run-plan.json", run_plan)
    cv_training.write_json(args.partition_plan, {"test": "partition"})
    checkpoint = tmp_path / "frozen-checkpoint.json"
    original_hash = cv_training.write_json(checkpoint, {"weights": {"weight": [1.0]}})
    freeze = {
        "runId": run_plan["runId"],
        "runPlanSha256": cv_training.sha256_file(tmp_path / "run-plan.json"),
        "partitionPlanSha256": cv_training.sha256_file(args.partition_plan),
        "sourceSha256": {"trainer": "frozen"},
        "files": {checkpoint.name: original_hash},
    }
    cv_training.write_json(tmp_path / "model-freeze.json", freeze)
    cv_training.write_json(checkpoint, {"weights": {"weight": [2.0]}})
    monkeypatch.setattr(cv_training, "verify_run_plan", lambda args: (run_plan, {}, [], {}))
    monkeypatch.setattr(cv_training, "source_hashes", lambda: {"trainer": "frozen"})

    def refuse_holdout_encoding(rows):
        pytest.fail("A modified frozen checkpoint must be rejected before holdout encoding.")

    monkeypatch.setattr(cv_training, "graph_pairs", refuse_holdout_encoding)
    with pytest.raises(ValueError, match="Frozen artifact changed"):
        cv_training.evaluate_final(args)
    assert not (tmp_path / "final-evaluation-started.json").exists()
