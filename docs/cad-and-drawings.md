# Executable CAD and dimensioned drawing tasks

This track contains **72 synthetic cases** across **12 part families × 3 evidence
modes × 2 parameter draws within each mode**. It adds actual solid construction,
STEP exchange and OpenCascade Boolean grading. It does not substitute textual
feature matching for geometric correctness.

## Parts and evidence modes

Part families: drilled plates, counterbored plates, capsule-slotted plates,
rectangular-pocket blocks, stepped shafts, flanged bushings, angle brackets and
open housings with a front-wall bore, rounded plates, chamfered pocket blocks,
tapered hubs and ruled-loft adapters. Features include blind/through cuts,
concentric steps, intersecting unions, holes on orthogonal axes, positioned
internal geometry, blank-edge rounds/chamfers, conical surfaces and multi-section
rectangular lofts. Unspecified edges remain sharp. These bounded operations do
not establish arbitrary edge selection, spline/guide-curve lofts, sheet bending,
assemblies or parametric feature-history coverage.

| Evidence mode | What the agent receives |
|---|---|
| Text and drawing | Human-readable dimensional description plus a raster engineering drawing |
| Drawing only | Raster views and dimension notes; no machine-readable target dimensions or feature recipe |
| Revision edit | An actual revision-A STEP solid, a change request and the released revision-B drawing |

Dimensions are drawn per case; the modes are not matched copies of the same two
parts. Mode summaries are descriptive, not a controlled estimate of how removing
text affects a model. Revision tasks accept a rebuilt matching solid: they do
not establish feature-history preservation or expert CAD editing proficiency.

Drawings include top, front, side and isometric hidden-line projections of the actual
B-rep, with human-readable dimensions and coordinate conventions. The PNGs carry
no hidden text, EXIF solution, target program or expected-volume metadata. Visible edges and face silhouettes are solid; hidden edges are dashed. These
are schematic engineering views, not complete drafting-standard or GD&T
packages. Dimension notes govern rather than pixels.

## Candidate artifacts

An agent returns exactly one JSON object:

- `{"program": <bounded CSG node>}`; or
- `{"step_base64": <base64 of a millimeter STEP artifact>}`.

The bounded declarative grammar supports boxes, axis-aligned cylinders and
conical frusta, unions, cuts, translations, all-edge fillets/equal-distance
chamfers and ruled lofts through two to four parallel XY rectangles. Edge
treatments operate on every edge of the child solid before later bores/pockets;
no arbitrary selector expression is evaluated. Loft sections must increase in Z,
with positive bounded dimensions and consistent corner order. It allows alternate feature trees that produce the same
solid. It is data, not Python: the grader never executes submitted source code.
Agents can use their own CAD tools externally and submit a STEP solid instead.
The STEP import path supports the disclosed millimeter exchange profile; it is
not a complete ISO STEP validation suite.

Every episode is one attempt. The agent receives no target solid, reference
recipe or live correctness feedback. A separate kernel worker validates and
constructs/imports the submitted solid, then measures it against the private
released target. Candidate STEP inputs are capped at five MB; CSG has at most
64 nodes, depth 12, and coordinates/dimensions bounded to 1,000 mm. CAD JSONL responses permit 7.1 MB to carry a five-MB STEP payload as base64;
other tracks retain their smaller default reply cap. Input transmission and
response reading share the agent wall-clock deadline. The default
worker timeout is 30 seconds. A timeout/process failure is an unsuccessful case.

The worker and input limits bound native geometry execution. They are not a
complete filesystem, memory or container security boundary. Credible untrusted
agent runs still need isolated agent/evaluator environments.

## Actual geometry scoring

Strict success requires all five checks:

1. Valid B-rep with exactly one solid.
2. Positive nonempty volume.
3. Boolean symmetric-difference volume no greater than
   `max(1e-5 mm^3, 1e-7 * target volume)`.
4. All six datum bounding coordinates within `1e-4 mm`.
5. Total volume difference within the same volume tolerance.

Each check contributes 20 partial points. **Strict success is the primary metric**;
a plausible outer box can earn basic validity points without matching the part.
Surface area, center of mass and volume IoU are diagnostics. A loose IoU threshold
is deliberately insufficient: a small missing hole can have IoU above 0.999 and
still fail the symmetric-difference criterion. Equal volume and bounds also do
not rescue a hole placed at the wrong location. No automatic alignment hides
wrong datums, translations or mirror errors.

Reference-consistency qualification constructs actual solids and uses supervised
workers to grade and replay every released case. Three geometric controls per
case test a stale revision, a shifted datum and an outer bounding box without
features (216 controls across 72 cases). Each of the 24 advanced-operation cases
also removes its edge treatment, replaces its frustum with a cylinder or replaces
its loft with a box; all such omissions must fail strict geometry matching.
Independent analytic fixtures check primitive/cut, frustum, rounded-box and
ruled-loft volumes. STEP round trips cover every advanced family. An alternative
feature tree must be accepted when its solid is equivalent.

## Canonical public assets and replay

Public PNGs and revision-A STEP files are frozen under
`src/faraday_manufacturing_benchmark/data/cad_assets/`. Their manifest records
content hashes, source-specification commitments, generator fingerprints and
kernel/rendering versions. The released target STEP/program is not exported in
these public packets. Reading packets does not require building target geometry.

The authoring command `python scripts/build_cad_assets.py` regenerates public
assets using pinned optional dependencies. STEP header timestamps and exporter
product counters are canonicalized; geometry entities are not modified. This
prevents process-local exporter labels from changing otherwise identical public
source bytes. The release manifest checks every asset hash and source commitment.

Replay verifies the exact frozen public input and candidate artifact, then reruns
the kernel. Checks and categorical outcomes must match. Floating diagnostics use
absolute tolerance `1e-8` and relative tolerance `1e-10` for native-kernel numerical
roundoff. A mismatched source, forged result or changed geometry fails replay.

## Commands

```bash
python -m pip install -e '.[dev,cad]'
otisbench list --track cad
otisbench export-cad --task cad-open_housing-drawing_only-01 --output-dir runs/housing-input
otisbench export-agent --task cad-drilled_plate-text_and_drawing-01 --output runs/cad-startup.json
otisbench cad --task cad-drilled_plate-text_and_drawing-01 \
  --agent-command 'python examples/cad_plate_agent.py' --output runs/cad-example.json
otisbench replay runs/cad-example.json
```

The JSONL transport is `faraday-manufacturing/1`, track `cad`. The public payload
contains image bytes in `drawing.base64` with MIME type and SHA-256; revision tasks
also contain `baseline_step`. A vision adapter should pass the image bytes to its
model, not expose the evaluator filesystem. The supplied example agent handles
text-described drilled plates only and makes no vision-performance claim.

Grade an independently prepared candidate without an agent:

```bash
otisbench grade-cad --task cad-drilled_plate-text_and_drawing-01 \
  --program candidate.json --output runs/candidate-result.json \
  --export-step runs/candidate.step
# Alternatively: --step candidate.step
```

Run native qualification with `python scripts/qualify_cad.py` and tests with
`python -m pytest tests/test_cad.py`. Without the optional CAD dependencies, the
CAD test module is explicitly skipped; a core-only green suite is not CAD
qualification. Reports remain separate from every other track.
