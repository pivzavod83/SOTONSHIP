# Paired-program training source

COBOL-JavaTrans, from [COBOL-Coder](https://github.com/COBOL-Coder/COBOL-Coder), contains 143 HumanEval-derived COBOL/Java task pairs. Collected 18 October 2026 at pinned commit `2b14b7bf7e55556205654c6f7657fa60e36251fa`. Dataset bytes SHA-256: `ff1b2e308ea006d905fd979103f32486c57d586c5fdbc0325a23f8ae23a6530d`.

The current GNN uses program correspondence labels from this benchmark with grouped train/validation/test tasks. These are small benchmark programs, not production banking migrations; no assertion is made that upstream translations have been independently audited by this project. They provide no node-level defect labels.

The [manifest](../../ml-engine/evaluation/paired-code/dataset-manifest.json), [splits](../../ml-engine/evaluation/paired-code/task-splits.json), [measured results](../../ml-engine/evaluation/paired-code/training-report.json), [Apache-2.0 notice](../../ml-engine/evaluation/paired-code/LICENSE-COBOL-Coder.txt), [underlying HumanEval MIT notice](../../ml-engine/evaluation/paired-code/LICENSE-HumanEval.txt), and [attribution](../../ml-engine/evaluation/paired-code/NOTICE.txt) are versioned. Raw source code remains in an ignored local cache; `scripts/fetch_paired_dataset.py` reproduces it by pinned URL.

Citation: Dau, Anh T. V.; Tan, Shin Hwei; Yang, Jinqiu; Bui, Nghi D. Q.; Nguyen, Anh Tuan (2026). *COBOL-Coder: Domain-Adapted Large Language Models for COBOL Code Generation and Translation*. arXiv:2604.03986. Underlying task attribution: OpenAI HumanEval.

Financial rates, IBM references, and AI-generated financial proof fixtures are separate sources and do not train this model.

The active v4 experiment reuses the frozen [120 development / 23 reserved IDs](../../ml-engine/evaluation/paired-code/cv-partition-plan.json) and intact task-similarity graph components. Four fixed improvements and a fresh control each retain five models fitted on 96 pairs and validated on 24, with no final fit on 120. All CCA statistics are fold-local. Checkpoints and the winner are chosen only from development CV before all candidate artifacts freeze and the 23 are assessed once. The selected regularized GNN scores 9/23 first matches; separate heads have the highest observed final learned-model score 11/23, but are not selected using that final result. See the [v4 report](../../ml-engine/evaluation/paired-code/cv-v4-candidates/final-evaluation-report.json).

All 23 were already evaluated in v1/v2/v3, and this comparison follows those results, so it is descriptive reused-benchmark evidence, not pristine unforeseen data. Source-pair labels remain unchanged; sequence-edge dropout creates training graph views, not additional authentic code pairs. Historical artifacts remain unchanged, and six old v1 test tasks remain in development.
