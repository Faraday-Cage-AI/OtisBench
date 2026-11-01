# Real photographed inspection development extension

This source-run extension adds the complete official **VisA one-class split**:
**10,821 real photographed images across 12 object categories**, including four
PCB categories, with **1,200 original anomalous-region masks**. The source
images, masks and published split are unchanged. This is upstream inspection
data, adding zero native cases or operational manufacturing workflows.

Source: [Amazon Science, SPot-the-Difference / VisA](https://github.com/amazon-science/spot-diff),
Zou, Jeong, Pemula, Zhang and Dabeer, ECCV 2022, [paper](https://arxiv.org/abs/2207.14315).
Dataset license: **CC BY 4.0**, preserved as `LICENSE-DATASET` in the source cache.
Faraday changes are image/mask resampling, opaque public identifiers, normal-only
fit/calibration partitioning, a local normal-appearance baseline and evaluation.

## Source and partition integrity

The official repository is pinned to `2a692ab575001cbde74d402d897a7286086c6199`.
The complete 1,929,840,640-byte official tar stream has SHA-256
`2eb8690c803ab37de0324772964100169ec8ba1fa3f7e94291c9ca673f40f362`.
Every required image and mask is retained byte-for-byte with an individual hash
and tar offsets. Streaming avoids keeping a duplicate archive. The acquisition
refuses duplicate/unsafe members and preserves a disk reserve.

The published test split stays intact: **2,162 photographs**, comprising 962
normal and 1,200 anomalous images. The 8,659 published normal training images are
partitioned by content hash into **6,920 fitting** and **1,739 normal calibration**
images. Identical content cannot cross fit/calibration; any exact image duplicate
across the official train/test boundary fails preparation. This is a content
duplicate check, not a guarantee against near duplicates, shared acquisition
conditions or prior public-data exposure.

The public input consists of `images.npy` (RGB uint8 tensors) and `index.json`
(opaque IDs, category, partition and array offsets). It omits source filenames,
image labels and defect masks. Evaluator files retain source mappings and truth.
Both are local development artifacts; the baseline process is **not OS-sandboxed**.
Its inspected implementation reads public inputs only. This does not certify
untrusted-agent access isolation.

## Baseline and metrics

The example fits a spatial RGB diagonal-Gaussian appearance model per category from normal fitting images. Thresholds use normal calibration images. Image and resampled-pixel AUROC use exact tie-aware ranking; reports also retain precision, recall, F1, and confusion counts. The baseline operates on 64×64 RGB arrays and corresponding area-resampled defect masks. Retain the resolution, split, threshold policy, and source hashes when reporting results.

## Commands

Preparation/qualification output directories are immutable. For a new source
acquisition and run, use fresh destinations:

```sh
python scripts/fetch_visual_inspection.py acquire --destination runs/visa-source-new
python scripts/visual_inspection_benchmark.py prepare \
  --source runs/visa-source-new --destination runs/visa-development-new
python scripts/qualify_visual_inspection.py run \
  --destination runs/visa-development-new --output-dir runs/visa-qualification-new
```

The offline audit verifies original image hashes, derived-cache commitments,
ID/partition/truth alignment, retained prediction/model bytes, replay agreement,
diagnostic construction and metric regrading. It does not refit or regenerate
all RGB inputs. Fresh qualification performs those more expensive checks.

The source cache contains pinned README, licenses, published split and metric
code for provenance; this implementation does not execute the upstream metric
script. The normal-appearance control uses local NumPy with no API calls or
pretrained weights. It is a learned statistical baseline, not a vision-language
agent or a matched-budget evaluation across the manufacturing suite.
