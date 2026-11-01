# Practitioner review protocol

Prepare source-bound review packets with public inputs, a submission template, and retained reviewer artifacts. The preparation tools create files locally.

## Reviewer instructions

1. Record the SHA-256 of `manifest.json` in `submission-template.json`.
2. Declare your role, relevant experience, relationship to the authors, prior
   exposure to reference solutions, and any human or AI assistance. Use an
   explicit statement such as "none" where appropriate; leave no declaration blank.
3. Work from the supplied case inputs before consulting reference solutions.
   These are public development cases, so this is a reference-withheld exercise,
   not a secret holdout. Disclose any earlier access to their solutions.
4. For each case you review, record an independently prepared answer, reasoning,
   and practical concerns. Remove unreviewed entries from your submission.
   Mark missing inputs, ambiguous rules, and suspected defects explicitly.
   For geometry, include your proposed program or artifact digest and describe
   how the coordinator can retrieve the exact artifact before references are disclosed.
5. Return the original submission and any answer artifacts to the coordinator.
   Freeze the submission and artifacts before reference disclosure. Preserve all
   later corrections as separate dated versions; do not replace the first answer.

The first and last catalog entry in each of nine native tracks form a purposive
18-case sample. It is not random or representative. Task IDs and public business
records may reveal scenario names. This packet excludes author reference answers,
evaluator traces, solved plans, private ERP snapshots and API credentials.

## What each review can establish

| Track | Supplied evidence | Requested scope |
|---|---|---|
| Engineering | Problem, numeric inputs and answer schema | Independent calculation and interpretation of the rule |
| CAD | Public drawing, instructions and starting STEP where applicable | Independent geometry and interpretation of dimensions |
| Procurement documents | Original synthetic PDFs and public reconciliation policy/schema | Independent reconciliation with page citations |
| Sensors | Raw CSV, asset facts and assessment policy | Independent signal assessment; no operational execution claim |
| Manufacturing workflow | Public task, tool contracts and opening system observations | Opening facts and rule/interface concerns only |
| Supply decisions | Public task, policy, tool contracts and opening observations | Opening facts and rule/interface concerns only |
| Procure-to-pay | Public task, tool contracts and opening observations | Opening facts and rule/interface concerns only; future documents absent |
| Execution | Public task wording and systems | Task wording only; no world observations supplied |
| Factory season | Week-zero public observation and action contract | Initial rules and economics only; no future demand or full season proof |

Opening observations are read from separately initialized worlds so tool calls do
not accidentally advance a shared clock. They are not an executable tool session.
A complete dynamic review requires a separately recorded interactive run, including
all public observations, decisions, tool results and final read-back. The existing
benchmark runners can support that later exercise. Do not mark an opening-snapshot
review as evidence of end-to-end feasibility or optimality.

ERP compatibility is a separate extension. This packet supplies no ERP review case;
three selected upstream author qualification runs do not imply independent review,
full ERP-Bench coverage, or a tenth native track.

## Coordinator workflow and custody

Prepare from the checkout after refreshing its release manifest:

```sh
.venv/bin/python scripts/build_manifest.py
.venv/bin/python scripts/review_kit.py build --output output/review/practitioner-v1
.venv/bin/python scripts/review_kit.py check --public output/review/practitioner-v1/public
```

Share only `reviewer-packet.zip` when separately authorized. Keep the coordinator
mapping private. Record the exact packet hash, invited reviewer's identity and
qualifications, relationship/conflicts, consent, and actual delivery separately.
No invitation or delivery is implied by building a packet.

Freeze an actual submission with:

```sh
.venv/bin/python scripts/review_kit.py freeze \
  --public output/review/practitioner-v1/public \
  --submission received-review.json \
  --receipt runs/reviews/reviewer-01-first-submission.json
```

The command verifies packet inventory, commitments, declarations and case IDs;
it retains original submission bytes in a non-overwriting receipt. It does not
grade answers or verify a person. Freeze any external answer artifacts separately
and bind their hashes to a follow-up receipt before reference disclosure. A hash
in prose without the retained artifact is insufficient to reproduce a CAD review.
Local timestamps are not trusted independent timestamps. File permissions alone
are not an immutable audit log; preserve receipts with a separately controlled
review coordinator or archive if tamper resistance is required.

Only after the first submission and artifacts are retained should the coordinator
disclose the case mapping, relevant reference logic, grading tolerances, and actual
outcomes. Record disclosure time and exact files/hashes in a separate event. The
current tool does not automate or attest disclosure chronology.

For every disagreement, retain the original answer, source citations, reviewer
rationale, reference/grader behavior, adjudicator identity, and resolution. Use
open, confirmed-defect, justified-alternative, or rejected-with-reason status.
Agreement with the author reference is not independent proof of correctness.
Keep physical feasibility, policy interpretation and economic preference separate.
A confirmed source or grader defect requires a versioned fix, requalification,
and renewed review of affected cases; an old packet never validates new source.

## Reporting rules

Report prepared, returned, identity-verified, independence-verified, adjudicated,
and accepted reviews separately. Record per-case scope and unresolved findings.
Self declarations, author controls, AI-generated submissions, and frozen hashes
must not increment independently verified practitioner coverage. This tooling
intentionally reports zero verified reviews and has no command to certify them.
A human coordinator must verify identity, expertise, independence, actual work
and adjudication evidence outside this syntactic intake tool.

A valid result may find defects rather than agree with the benchmark. Eighteen
reviewed samples, even if independently verified, do not validate all cases or
establish a worldwide comprehensiveness ranking.
