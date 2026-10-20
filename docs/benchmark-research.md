# Research behind the benchmark roadmap

Sources checked on **20 October 2026** against official conference proceedings or the conference's paper page. The structured source inventory is [research.json](../backend/benchmark-ui/research.json), which the local benchmark site displays. This catalogue is AI-generated research synthesis and needs human review. It introduces no model weights, new accuracy measurements, or changes to deployed inference.

## What the papers support

| Peer-reviewed paper | Useful idea | Boundary of the evidence |
| --- | --- | --- |
| Chakaravarthy et al., [Enterprise-Scale COBOL-to-Java Translation](https://doi.org/10.1145/3786583.3786915), ICSE 2026 Software Engineering in Practice | Combine program analysis with LLM translation and application-level design. | Translation research; LLM-judged functional quality is not independent formal equivalence. |
| Gandhi et al., [Low-resource COBOL translation and Java refinement](https://conf.researchr.org/details/icse-2024/llm4code-2024-papers/22/Translation-of-Low-Resource-COBOL-to-Logically-Correct-and-Readable-Java-leveraging-H), LLM4Code workshop at ICSE 2024 | Use execution feedback while refining translated Java. | A workshop translation study using algorithmic examples; finite-test success is not universal correctness. |
| Chen and Guestrin, [XGBoost](https://doi.org/10.1145/2939672.2939785), KDD 2016 | A regularized tree-boosting classifier for structured differences. | A general method, not evidence of COBOL translation accuracy. |
| Grinsztajn, Oyallon and Varoquaux, [Tree models versus deep learning on tabular data](https://proceedings.neurips.cc/paper_files/paper/2022/hash/0378c7692da36807bdec87ab043cdadc-Abstract-Datasets_and_Benchmarks.html), NeurIPS 2022 Datasets and Benchmarks | Establish a competitive tree baseline with fair tuning. | Their benchmark differs substantially from our tiny pilot. |
| Li et al., [Graph Matching Networks](https://proceedings.mlr.press/v97/li19d.html), ICML 2019 | Compare two graphs jointly through cross-graph attention. | Retrieval/similarity results do not establish behavioral equivalence. |
| Zhou et al., [Devign](https://papers.neurips.cc/paper/2019/hash/49265d2447bc3bbfe9e76306ce40a31f-Abstract.html), NeurIPS 2019 | Combine syntax, data flow and control flow for classification. | C vulnerabilities; neither COBOL-to-Java defects nor exact line labels. |
| Guo et al., [GraphCodeBERT](https://iclr.cc/virtual/2021/poster/2598), ICLR 2021 | Pretrain representations using data-flow structure. | The [released model's language list](https://github.com/microsoft/CodeBERT) excludes COBOL. |
| Allamanis, Jackson-Flux and Brockschmidt, [Self-Supervised Bug Detection and Repair (BugLab)](https://proceedings.neurips.cc/paper/2021/hash/ea96efc03b9a050d895110db8c4af057-Abstract.html), NeurIPS 2021 | Learn from difficult generated training bugs. | Python results; generated examples require explicit provenance and do not substitute for natural failures. |
| Angelopoulos et al., [Conformal Risk Control](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f3549ef9b5ff520a7e41ff3cc306ab2b-Abstract-Conference.html), ICLR 2024 | Calibrate a decision rule against an expected-loss target. | Requires independent calibration and justified sampling assumptions; no per-program zero-error guarantee. |

All nine entries refer to accepted conference or workshop publications, rather than treating a preprint alone as evidence of peer review. The COBOL refinement paper is explicitly a **workshop paper**, not an ICSE main-track paper; the [2024 workshop call](https://llm4code.github.io/2024/call/) states its double-blind review process. The [official ICSE 2026 programme](https://conf.researchr.org/details/icse-2026/icse-2026-software-engineering-in-practice/56/Enterprise-Scale-COBOL-to-Java-Translation-LLMs-Augmented-with-Program-Analysis) confirms the enterprise translation paper's SEIP track. GraphCodeBERT's official ICLR poster page supplies the venue, year, authors and paper link; the author-maintained repository separately supplies its language list. None supplies measured defect performance for this project.

The two directly related studies establish that COBOL-to-Java migration research exists; they should inform our design and prevent novelty claims that ignore prior work. They investigate generation/refinement, while our proposed experiment concerns detection and localization for a supplied pair. This distinction does not establish that our approach is novel or better: those require a broader review and an independently measured comparison.

## Prioritized experiments

These are **proposals, not trained versions**. Priorities are our engineering judgment, informed by the papers rather than prescribed by them.

1. **Explicit semantic differences, then trees.** Improve numeric-unit normalization, ordered operand comparison, receiving-type effects, rounding location and output dependencies. Compare shallow XGBoost with regularized logistic regression under identical family splits and tuning budgets. Ambiguous semantics require abstention.
2. **Output dependency slices and localization.** Work backwards from observable outputs through data and control edges. Preserve crossing dependencies and allow overlapping slices. First assess candidate-region coverage; then evaluate pair detection and localization independently. This slicing design is our proposed adaptation, not a reproduction of Devign.
3. **A paired defect GNN.** Use joint cross-graph reasoning and defect/location supervision. Keep the existing program-retrieval GNN separate. A high similarity score can hide a critical semantic change, so similarity alone is the wrong acceptance criterion.
4. **Confirmed difficult examples and calibration.** Collect reviewed translation failures with corrected Java, common-input witnesses, compiler settings and provenance. Include difficult correct pairs. If controlled mutations supplement training, label them synthetic. Investigate risk calibration only after collecting enough independent calibration families.

## Rules for a defensible next comparison

Keep all variants and near duplicates of a source family together. Freeze the protocol before fitting; fit preprocessing, representation learning and threshold selection only within the appropriate development partitions. Reserve new families for final testing and, where required, independent calibration. The existing known regression examples remain reusable regression evidence, not a fresh holdout.

Report defect-positive recall with its numerator and denominator, false negatives, precision, review workload, extraction abstentions and localization Hit@1/Hit@3. Assess candidate coverage and numeric-semantic invariance separately from learned accuracy. Do not claim higher recall merely by sending every pair to review; show how much useful review reduction accompanies it. The number of independent families matters more than multiplying variants of the same source.

Passing finite tests supplies scoped behavioral evidence, not universal equivalence. Extraction coverage is not compiler validation. A low model score never authorizes migration acceptance; bounded formal verification and human review retain their separate roles.
