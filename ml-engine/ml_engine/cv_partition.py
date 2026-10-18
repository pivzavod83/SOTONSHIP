"""Freeze leakage-aware task-graph partitions without fitting or scoring a model.

Vertices are complete COBOL/Java source pairs.  Near-duplicate source pairs form
indivisible connected components; individual program graphs are never cut into
training and evaluation nodes.  This is dataset graph partitioning, not a claim
that approximate program graphs establish semantic equivalence.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from .code_graph import CodeGraph, KEYWORDS, RELATIONS, TOKEN, build_graph, clean_source

PINNED_DATASET_SHA256 = "ff1b2e308ea006d905fd979103f32486c57d586c5fdbc0325a23f8ae23a6530d"
DATASET_SIZE = 143
HOLDOUT_SIZE = 23
FOLDS = 5
SHINGLE_SIZE = 5
NEAR_DUPLICATE_JACCARD = 0.80
WL_ROUNDS = 3


def _json_hash(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _task_order(task_id: str):
    """Human-readable numeric task order, with a deterministic generic fallback."""
    prefix, separator, suffix = task_id.rpartition("/")
    return (prefix, 0, int(suffix)) if separator and suffix.isdigit() else (task_id, 1, 0)


def _validate_rows(rows: list[dict]) -> list[str]:
    if len(rows) != DATASET_SIZE:
        raise ValueError(f"Expected {DATASET_SIZE} original paired tasks")
    ids = []
    for row in rows:
        task_id = row.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("Every source pair needs a nonempty task_id")
        for language in ("COBOL", "Java"):
            source = row.get(f"{language}_canonical_solution")
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f"Missing {language} source for {task_id}")
        ids.append(task_id)
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate task IDs are not independent source pairs")
    return ids


def normalised_shingles(source: str, language: str) -> set[tuple[str, ...]]:
    """Comment-free, identifier-normalised lexical near-duplicate detector."""
    tokens = TOKEN.findall(clean_source(source, language).lower())
    words = ["IDENT" if re.match(r"[a-z_]", token) and token not in KEYWORDS else token
             for token in tokens]
    return {tuple(words[i:i + SHINGLE_SIZE])
            for i in range(max(1, len(words) - SHINGLE_SIZE + 1))}


def graph_fingerprint(graph: CodeGraph) -> str:
    """Three-round relation-aware Weisfeiler-Lehman fingerprint.

    Node order and identifier spelling are absent.  Exact fingerprint equality
    conservatively groups possible duplicates; it does not certify isomorphism
    or program equivalence.  Numeric graph features retain eight decimal places.
    """
    labels = [_json_hash(feature.round(8).tolist()) for feature in graph.x]
    for _ in range(WL_ROUNDS):
        neighbors = [[] for _ in labels]
        for relation in RELATIONS:
            for left, right in graph.edges[relation]:
                neighbors[int(left)].append((relation, labels[int(right)]))
        labels = [_json_hash([label, sorted(adjacent)])
                  for label, adjacent in zip(labels, neighbors)]
    return _json_hash(sorted(labels))


def graph_groups(rows: list[dict]) -> tuple[list[list[str]], list[dict]]:
    """Return connected components and auditable similarity-graph edges."""
    _validate_rows(rows)
    ordered = sorted(rows, key=lambda row: _task_order(row["task_id"]))
    identifiers = [row["task_id"] for row in ordered]
    shingles, fingerprints = {}, {}
    for language, field_language in (("cobol", "COBOL"), ("java", "Java")):
        sources = [row[f"{field_language}_canonical_solution"] for row in ordered]
        shingles[language] = [normalised_shingles(source, language) for source in sources]
        fingerprints[language] = [graph_fingerprint(build_graph(source, language)) for source in sources]

    parent = list(range(len(ordered)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    edges = []
    for left in range(len(ordered)):
        for right in range(left):
            reasons = []
            for language in ("cobol", "java"):
                first, second = shingles[language][left], shingles[language][right]
                jaccard = len(first & second) / max(1, len(first | second))
                if jaccard >= NEAR_DUPLICATE_JACCARD:
                    reasons.append({"language": language, "kind": "normalised-token-shingle",
                                    "jaccard": round(jaccard, 6)})
                if fingerprints[language][left] == fingerprints[language][right]:
                    reasons.append({"language": language, "kind": "exact-wl-graph-fingerprint"})
            if reasons:
                parent[find(left)] = find(right)
                edges.append({"taskIds": [identifiers[right], identifiers[left]], "reasons": reasons})
    components = {}
    for index, task_id in enumerate(identifiers):
        components.setdefault(find(index), []).append(task_id)
    return sorted(components.values(), key=lambda group: _task_order(group[0])), edges


def _seeded_order(seed: int, purpose: str, group: list[str]) -> str:
    return _json_hash({"seed": seed, "purpose": purpose, "taskIds": sorted(group, key=_task_order)})


def _exact_holdout(groups: list[list[str]], prior_test: set[str], seed: int) -> list[list[str]]:
    eligible = [group for group in groups if set(group) <= prior_test]
    eligible.sort(key=lambda group: _seeded_order(seed, "final-holdout", group))
    # Deterministic subset sum preserves whole groups and the exact requested size.
    # Existing states are not replaced: fixed hash order, never retrieval scores.
    states = {0: ()}
    for index, group in enumerate(eligible):
        for count, selected in list(states.items()):
            size = count + len(group)
            if size <= HOLDOUT_SIZE and size not in states:
                states[size] = (*selected, index)
        if HOLDOUT_SIZE in states:
            return [eligible[index] for index in states[HOLDOUT_SIZE]]
    raise ValueError("Cannot select exactly 23 prior-test tasks without cutting a graph component")


def _balanced_folds(groups: list[list[str]], seed: int) -> list[list[str]]:
    capacity = (DATASET_SIZE - HOLDOUT_SIZE) // FOLDS
    parts = [[] for _ in range(FOLDS)]
    ordered = sorted(groups, key=lambda group: (-len(group), _seeded_order(seed, "cv-groups", group)))
    fold_order = sorted(range(FOLDS), key=lambda fold: _json_hash([seed, "cv-fold", fold]))
    for group in ordered:
        eligible = [fold for fold in fold_order if len(parts[fold]) + len(group) <= capacity]
        if not eligible:
            raise ValueError("Cannot form five balanced whole-component folds of 24 tasks")
        fold = min(eligible, key=lambda index: len(parts[index]))
        parts[fold].extend(group)
    if any(len(part) != capacity for part in parts):
        raise ValueError("Whole-component folds did not attain the exact required sizes")
    return [sorted(part, key=_task_order) for part in parts]


def build_partition_plan(rows: list[dict], prior_split: dict, seed: int = 431, *,
                         dataset_sha256: str = PINNED_DATASET_SHA256,
                         prior_split_sha256: str | None = None) -> dict:
    """Freeze 120 development / 23 prior-test tasks and five grouped folds.

    This function reads source pairs and prior split IDs only.  It never reads
    trained weights, predictions, retrieval ranks, or evaluation reports.
    """
    task_ids = _validate_rows(rows)
    splits = prior_split.get("splits", {})
    prior_lists = [splits.get(name) for name in ("train", "validation", "test")]
    if any(not isinstance(part, list) for part in prior_lists):
        raise ValueError("Prior split must include train, validation and test task IDs")
    prior_ids = [task_id for part in prior_lists for task_id in part]
    if len(prior_ids) != len(set(prior_ids)) or set(prior_ids) != set(task_ids):
        raise ValueError("Prior split must cover every original task exactly once")
    if len(splits["test"]) != 29:
        raise ValueError("Expected the original 29-task test split for exposure accounting")
    if dataset_sha256 != PINNED_DATASET_SHA256:
        raise ValueError("Dataset must match the pinned 143-pair benchmark SHA-256")
    groups, edges = graph_groups(rows)
    prior_test = set(splits["test"])
    held_groups = _exact_holdout(groups, prior_test, seed)
    holdout = sorted([task_id for group in held_groups for task_id in group], key=_task_order)
    holdout_set = set(holdout)
    development_groups = [group for group in groups if not set(group) & holdout_set]
    development = sorted([task_id for group in development_groups for task_id in group], key=_task_order)
    validation_folds = _balanced_folds(development_groups, seed)
    folds = [{"fold": index + 1, "validationTaskIds": validation,
              "trainTaskIds": sorted(set(development) - set(validation), key=_task_order)}
             for index, validation in enumerate(validation_folds)]
    plan = {
        "version": "paired-gnn-grouped-cv-v2", "datasetSha256": dataset_sha256,
        "rowContentSha256": _json_hash(sorted(rows, key=lambda row: _task_order(row["task_id"]))),
        "seed": seed, "priorSplitSha256": prior_split_sha256 or _json_hash(prior_split),
        "priorSplitHashEncoding": "raw-file-bytes" if prior_split_sha256 else "canonical-json",
        "developmentTaskIds": development, "finalHoldoutTaskIds": holdout, "folds": folds,
        "k": FOLDS,
        "kRationale": "Five folds retain 96 training pairs and 24 validation queries per run; ten folds would leave only 12 validation queries. Every development task validates exactly once.",
        "graphPartitioning": {
            "method": "Balanced whole-connected-component partition of a task-similarity graph; complete paired program graphs remain intact.",
            "vertices": len(rows), "groups": groups, "edges": edges,
            "groupSizeCounts": {str(size): count for size, count in sorted(Counter(map(len, groups)).items())},
            "edgeRule": {"languages": ["cobol", "java"], "combination": "OR",
                         "normalisedTokenShingleSize": SHINGLE_SIZE,
                         "minimumJaccard": NEAR_DUPLICATE_JACCARD,
                         "exactSemanticGraphFingerprint": {"method": "relation-aware Weisfeiler-Lehman", "rounds": WL_ROUNDS}},
            "holdoutSelection": "Fixed seed/hash ordering of whole components entirely inside the original 29-task test split; exact subset sum to 23; no prediction or metric access.",
            "foldAssignment": "Descending component size, seed/hash tie order, then least-loaded fold with capacity 24.",
            "limitations": "Conservative lexical/heuristic-graph grouping may miss semantic duplicates; it does not establish equivalent algorithms."
        },
        "exposureAudit": {
            "priorTestTaskIds": sorted(prior_test, key=_task_order), "priorRunObserved": True,
            "previouslyTrainedTasksMovedToHoldout": False,
            "newHoldoutSelectionUsesPriorScores": False,
            "disclosure": "The 23 final tasks were previously evaluated in the earlier 29-task test split. They are excluded from this retraining and all cross-validation/checkpoint selection, but are not pristine unseen external data. The other six prior-test tasks enter development only after this plan is frozen."
        },
        "selectionProtocol": "Freeze this plan before new training; choose training duration using only the five development folds; refit on all 120 development pairs; evaluate the 23 held-out pairs once after choices freeze.",
        "retrievalCandidateCounts": {"crossValidation": 24, "finalHoldout": 23},
    }
    validate_partition_plan(plan, rows)
    return plan


def validate_partition_plan(plan: dict, rows: list[dict]) -> None:
    """Reject overlap, missing tasks, altered sources, or cut graph components."""
    task_ids = set(_validate_rows(rows))
    if plan.get("datasetSha256") != PINNED_DATASET_SHA256:
        raise ValueError("Partition plan dataset SHA-256 does not match the pinned corpus")
    if plan.get("rowContentSha256") != _json_hash(sorted(rows, key=lambda row: _task_order(row["task_id"]))):
        raise ValueError("Partition plan source rows have changed")

    def unique_ids(value, size, label):
        if not isinstance(value, list) or len(value) != size or len(set(value)) != size:
            raise ValueError(f"{label} must contain exactly {size} unique task IDs")
        if not set(value) <= task_ids:
            raise ValueError(f"{label} contains unknown task IDs")
        return set(value)

    development = unique_ids(plan.get("developmentTaskIds"), 120, "Development partition")
    holdout = unique_ids(plan.get("finalHoldoutTaskIds"), 23, "Final holdout")
    if development & holdout or development | holdout != task_ids:
        raise ValueError("Development and holdout must be disjoint and cover all source pairs")
    prior_test = unique_ids(plan.get("exposureAudit", {}).get("priorTestTaskIds"), 29, "Prior test partition")
    if not holdout <= prior_test:
        raise ValueError("Final holdout must use only original test tasks")
    if plan.get("k") != FOLDS or len(plan.get("folds", [])) != FOLDS:
        raise ValueError("Expected exactly five cross-validation folds")
    validation_counts = Counter()
    fold_assignments = []
    for index, fold in enumerate(plan["folds"], 1):
        if fold.get("fold") != index:
            raise ValueError("Fold indices must be 1 through 5 in order")
        train = unique_ids(fold.get("trainTaskIds"), 96, "Fold training partition")
        validation = unique_ids(fold.get("validationTaskIds"), 24, "Fold validation partition")
        if train & validation or train | validation != development:
            raise ValueError("Each fold must split only the complete development partition")
        validation_counts.update(validation)
        fold_assignments.append((train, validation))
    if validation_counts != Counter({task_id: 1 for task_id in development}):
        raise ValueError("Every development task must validate in exactly one fold")
    groups, edges = graph_groups(rows)
    recorded = plan.get("graphPartitioning", {})
    if recorded.get("groups") != groups or recorded.get("edges") != edges:
        raise ValueError("Recorded graph components/edges do not match actual source pairs")
    for group in groups:
        members = set(group)
        if members & holdout and not members <= holdout:
            raise ValueError("A graph component crosses the final holdout boundary")
        for train, validation in fold_assignments:
            if members & validation and not members <= validation:
                raise ValueError("A graph component was cut across a validation fold")
            if members & train and not members <= train:
                raise ValueError("A graph component was cut across a training fold")
    # Recompute score-independent assignment, catching manual score-based swaps.
    expected_holdout = set(task_id for group in _exact_holdout(groups, prior_test, plan["seed"]) for task_id in group)
    if holdout != expected_holdout:
        raise ValueError("Holdout differs from the fixed score-independent hash selection")
    expected_folds = _balanced_folds([group for group in groups if not set(group) & holdout], plan["seed"])
    if [fold["validationTaskIds"] for fold in plan["folds"]] != expected_folds:
        raise ValueError("Fold assignment differs from the deterministic balanced graph partition")
