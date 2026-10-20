"""Protocol and safety tests using tiny stub graphs, never fitting the pilot data."""
from pathlib import Path
from types import SimpleNamespace
import json

import numpy as np
import pytest

from scripts import benchmark_extractor_v2 as benchmark


def graph():
    return SimpleNamespace(global_x=np.array([0.1, 0.2]), candidate_x=np.array([[0.1, 0.2], [0.3, 0.4]]),
                           candidates=[(0, 0), (None, 0)], coverage={"status": "test fixture"},
                           cobol=[SimpleNamespace(start=2, end=2)], java=[SimpleNamespace(start=3, end=4)])


def row(family="F001", label=1, covered=True):
    return {"family": family, "variant": f"{family}-fixture", "label": label, "covered": covered,
            "graph": graph(), "line_y": np.array([0, 1]) if covered else np.empty(0, dtype=int)}


def test_protocol_predeclares_fixed_settings_and_reused_test_without_fitting():
    protocol = benchmark.protocol()
    assert protocol["model"]["C"] == .1
    assert protocol["operatingThreshold"] == .25
    assert "REUSED" in protocol["testPolicy"]
    assert "no threshold" in protocol["thresholdSelection"]
    assert set(protocol["arms"]) == {"v1-refit-control", "typed-v2"}
    assert protocol["safetyAuthority"] == {"aiIsProof": False, "canApproveCode": False, "canAuthorizePatch": False}


def test_portable_logistic_score_has_defect_positive_direction():
    model = {"mean": [0.], "scale": [2.], "coef": [1.], "intercept": 0.}
    assert benchmark.linear_score(np.array([2.]), model) > .5
    assert benchmark.linear_score(np.array([-2.]), model) < .5


def test_unsupported_graph_always_abstains_to_review_without_using_a_model():
    result = benchmark.predict(row(covered=False), [])
    assert result == {"score": None, "decision": "REVIEW_REQUIRED", "abstained": True, "lineScores": None}


def test_inner_crossfit_excludes_both_inner_and_outer_held_out_families(monkeypatch):
    rows = [row(family, label) for family in ("F001", "F002", "F003", "F006", "F007", "F008") for label in (0, 1)]
    ranker_fits = []
    classifier_fits = []

    def ranker(fitting):
        families = sorted({item["family"] for item in fitting})
        ranker_fits.append(families)
        return {"fixture": True}

    def classifier(x, y):
        classifier_fits.append((x, y))
        return {"fixture": True}

    monkeypatch.setattr(benchmark, "fit_ranker", ranker)
    monkeypatch.setattr(benchmark, "fit_linear", classifier)
    monkeypatch.setattr(benchmark, "linear_score", lambda x, state: np.full(len(x), .3))
    result = benchmark.fit_fold(rows, ("F001", "F006"))
    assert len(result["innerCrossfit"]) == 4
    for record, actual_fitting in zip(result["innerCrossfit"], ranker_fits):
        assert record["heldOutFamily"] not in actual_fitting
        assert not {"F001", "F006"}.intersection(actual_fitting)
        assert len(actual_fitting) == 3
    assert ranker_fits[-1] == ["F002", "F003", "F007", "F008"]
    assert len(classifier_fits) == 1
    assert classifier_fits[0][0].shape == (8, 6)
    assert classifier_fits[0][1].tolist() == [0, 1] * 4


def test_metrics_separate_abstention_review_workload_from_classifier_accuracy():
    rows = [row(label=1), row("F002", label=1, covered=False), row("F003", label=0), row("F004", label=0, covered=False)]
    predictions = [{"score": .1, "decision": "NO_DEFECT_SIGNAL", "abstained": False, "lineScores": np.array([.8, .2])},
                   benchmark.predict(rows[1], []),
                   {"score": .9, "decision": "REVIEW_REQUIRED", "abstained": False, "lineScores": np.array([.8, .2])},
                   benchmark.predict(rows[3], [])]
    result = benchmark.summarize(rows, predictions)
    assert result["coverage"]["abstainedPairs"] == 2
    assert result["reviewTriageIncludingAbstentions"]["confusion"] == {"truePositive": 1, "trueNegative": 0, "falsePositive": 2, "falseNegative": 1}
    assert result["coveredClassifierOnly"]["accuracy"] == 0
    assert result["reviewTriageIncludingAbstentions"]["reviewWorkloadFraction"] == .75
    assert result["reviewTriageIncludingAbstentions"]["autonomousAcceptances"] == 0
    assert result["localizationWeakLabels"]["defectivePairs"] == 2
    assert result["localizationWeakLabels"]["hitAt3"] == .5
    assert not result["acceptanceAuthority"]


def test_legacy_arm_does_not_claim_strict_parse_coverage():
    item = row()
    prediction = {"score": .9, "decision": "REVIEW_REQUIRED", "abstained": False, "lineScores": np.array([.1, .9])}
    coverage = benchmark.summarize([item], [prediction], "v1-refit-control")["coverage"]
    assert coverage["strictCoverageProvided"] is False
    assert coverage["supportedPairs"] is None
    assert coverage["computedPairs"] == 1


def test_all_review_is_a_trivial_workload_baseline_not_acceptance():
    result = benchmark.classification_metrics([0, 0, 1, 1], [True] * 4)
    assert result["recall"] == 1
    assert result["precision"] == result["accuracy"] == .5
    assert result["reviewWorkloadFraction"] == 1
    assert result["autonomousAcceptances"] == 0


def test_once_only_regression_marker_refuses_repeat_before_reading_data(tmp_path):
    (tmp_path / "regression-test-evaluation.json").write_text('{"status":"STARTED"}')
    with pytest.raises(ValueError, match="repeated evaluation is refused"):
        benchmark.evaluate_regression_test(tmp_path)


def test_existing_model_refuses_retraining_before_loading_extractors(tmp_path):
    (tmp_path / "model.json").write_text('{}')
    with pytest.raises(ValueError, match="already trained"):
        benchmark.train(tmp_path)


def test_modified_frozen_implementation_prevents_assessment(tmp_path, monkeypatch):
    for name in ("model.json", "protocol.json", "contract-diagnostics.json", "data.json", "split.json"):
        (tmp_path / name).write_text('{}')
    monkeypatch.setattr(benchmark, "DATA", tmp_path / "data.json")
    monkeypatch.setattr(benchmark, "PLAN", tmp_path / "split.json")
    frozen = {"modelSha256": benchmark.digest(tmp_path / "model.json"), "datasetSha256": benchmark.digest(benchmark.DATA),
              "splitPlanSha256": benchmark.digest(benchmark.PLAN), "protocolSha256": benchmark.digest(tmp_path / "protocol.json"),
              "contractAuditSha256": benchmark.digest(tmp_path / "contract-diagnostics.json"),
              "implementationHashes": {"extractor": "old"}}
    (tmp_path / "frozen-artifact.json").write_text(json.dumps(frozen))
    monkeypatch.setattr(benchmark, "implementation_hashes", lambda: {"extractor": "changed"})
    with pytest.raises(ValueError, match="implementation"):
        benchmark.evaluate_regression_test(tmp_path)
    assert not (tmp_path / "regression-test-evaluation.json").exists()


def test_metric_length_mismatch_is_rejected():
    with pytest.raises(ValueError, match="different lengths"):
        benchmark.classification_metrics([1], [])


def test_source_only_contract_regressions_are_separate_from_accuracy_data():
    report = benchmark.contract_diagnostics()
    assert report["fixtureCount"] == 8
    assert report["failedContracts"] == 0, [(item["fixtureId"], item["v2Statuses"]) for item in report["results"] if not item["passed"]]
    assert report["modelTrained"] is report["codeExecuted"] is report["accuracyDatasetChanged"] is False
