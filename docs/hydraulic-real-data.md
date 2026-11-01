# Real hydraulic test-rig extension

This separate extension uses the [UCI Condition monitoring of hydraulic systems
dataset](https://archive.ics.uci.edu/dataset/447/condition+monitoring+of+hydraulic+systems),
DOI [10.24432/C5CW21](https://doi.org/10.24432/C5CW21), by Helwig, Pignanelli and
Schuetze (2015), licensed CC BY 4.0. Upstream measurements come from a controlled
hydraulic test rig with varied component settings. This source-run tier uses the original measurements and condition labels.

## Task

Given a complete 60-second cycle, predict four annotated experimental conditions:
cooler level, valve level, internal pump leakage level and accumulator pressure
level. The task is retrospective condition classification. The source does not
supply remaining useful life, causal repair outcomes, or economic maintenance
policy rewards; do not report those capabilities from these scores.

All 2,205 upstream cycles are retained. The source stability flag marks 1,449
cycles stable and 756 potentially unsettled. It is retained only for evaluator
stratification, never as an input feature or prediction target. The raw-data
interface exposes 14 physical pressure, power, flow, temperature and vibration
channels at their original sampling rates. Derived/virtual CE, CP and SE channels
are excluded. Raw arrays retain the parsed source float64 values; no resampling,
interpolation or per-cycle normalization is applied.

Each cycle also supplies 112 fixed summary features: per channel, population
mean/std, min/max, quartiles and second-half minus first-half mean. The feature
function uses no labels or fitted statistics. It sees the entire recorded cycle,
so it cannot establish online or early-warning performance.

## Grouped evaluation

All occurrences of a particular four-component condition combination stay in one
partition, including stable and unstable variants. A predeclared SHA-256 ordering
of the 144 combinations yields:

| Partition | Condition groups | Cycles | Stable cycles |
|---|---:|---:|---:|
| Training | 86 | 1,150 | 869 |
| Validation | 28 | 505 | 280 |
| Test | 30 | 550 | 300 |

Every partition contains all levels of all four targets. Counts follow the fixed
group rule; they are not equal-sized random cycle splits. Repeated occurrences
of one setting cannot leak across these partitions. This does not eliminate
single-rig bias, temporal drift, correlated experiments, or contamination from
this publicly available source. This is a **public development evaluation**, not
a secret holdout, structurally novel manufacturing workflow, or unseen-factory test.

Public files contain training/validation labels, predictor vectors and opaque
cycle handles. Test labels, original source cycle indices, group membership and
raw source arrays remain in the evaluator directory. A local macOS standard-library
agent receives only the training data and then one test observation at a time.
It may request paginated raw samples for that active cycle. It receives no test
labels, scores, other test-cycle records or feedback while running. Evaluation
occurs after the process is closed. The existing sandbox denies host data/source
reads and networking; it does not erase prior knowledge or prevent a previously
memorized public dataset from being recognized.

## Baselines and metrics

The supplied offline standard-library baseline implements two fixed methods:

- Training priors: Laplace-smoothed class counts, with no predictor dependence.
- Seven nearest neighbors: Euclidean distance on training-standardized summaries;
  seven votes and Laplace smoothing for each target's probabilities. Zero-variance
  training dimensions use unit scale. It never refits on test or validation data.

No hyperparameter search or validation selection is performed. These are local
supervised classifiers, not language models, agents executing maintenance, or
release-wide model results. Both receive identical training rows, feature schema,
test cycles and sandbox constraints. Provider cost is zero; wall times include
transport, parsing, fitting and inference and are not pure kernel latency.

Primary accuracy is exact agreement on all four targets. Per target, reports
include accuracy, balanced accuracy, macro-F1, confusion/support counts, negative
log likelihood, multiclass Brier score and 10-bin confidence calibration error.
Balanced accuracy averages classes with observed support; macro-F1 retains all
declared levels with zero F1 for an unsupported/unpredicted level. The Brier score
is the unnormalized sum over classes (range 0 to 2). ECE is sample weighted with
fixed [0,.1), ..., [.9,1] bins and is descriptive, not a calibration guarantee.
Metrics are also reported separately for stable and potentially unsettled cycles.
The scores use repeated cycles, so do not treat them as independent-trial
confidence intervals. Missing predictions cannot disappear from denominators;
a stopped run retains partial receipts and has no complete score.

## Reproduction and custody

```sh
python -m pip install -e '.[dev,real-data]'
python scripts/hydraulic_benchmark.py fetch --archive runs/hydraulic-uci-447.zip
python scripts/build_manifest.py
python scripts/hydraulic_benchmark.py prepare --output runs/hydraulic-development-v1
python scripts/hydraulic_benchmark.py run --input runs/hydraulic-development-v1 \
  --agent-file examples/hydraulic_knn_agent.py --method majority \
  --output reports/hydraulic-prior-baseline.json
python scripts/hydraulic_benchmark.py run --input runs/hydraulic-development-v1 \
  --agent-file examples/hydraulic_knn_agent.py --method knn \
  --output reports/hydraulic-knn-baseline.json
python scripts/qualify_hydraulics.py
python scripts/hydraulic_benchmark.py regrade --input runs/hydraulic-development-v1 \
  --episode reports/hydraulic-knn-baseline.json
```

The archive is pinned by SHA-256, and parsed source member hashes, dimensions,
feature definition, file hashes, group assignments and source-script hashes are
retained. `prepare` refuses to overwrite a frozen directory. Agent source and
sandbox metadata, predictions and public raw-stream observations are retained
per run. Regrading verifies source files and recomputes reported metrics from
retained predictions; it is not a new model inference run. Retain the private
local artifacts to reproduce it. Scripts/measurements are not automatically
included in the native-track wheel. The sandbox is macOS-only and standard-library
only; unsupported platforms fail without falling back to an unisolated agent.
