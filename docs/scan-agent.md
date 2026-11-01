# Public scan reconciliation control

This separate control evaluates the same 48 presentations / 16 underlying public
development scenarios as the [synthetic scan study](supplier-scans.md). It adds
zero native cases and does not replace the original failed OCR/parser result.
The policy was developed after inspecting the development failures and sample
pages; these are not blind or held-out results.

## Public tool and isolated policy

`scan_ocr_tools.py` receives only a PNG path. It estimates skew from horizontal
ink concentration over a bounded angle search, removes isolated single dark
pixels, estimates smooth page illumination, normalizes the raster by that
background, doubles image resolution, and runs Tesseract English / PSM 6. It
retains raw OCR output, errors, estimated angle and elapsed time. Capture profile,
source business records, reference answers and graded outcomes do not enter the
preprocessing function. It does not insert missing text or correct identifiers.

The standalone standard-library policy receives only document IDs, page numbers
and public OCR text through JSONL. It runs under the existing macOS offline
sandbox. It cannot read the evaluator, source scenarios or retained evaluation
answers. Four actual private files have host-read positive controls and sandbox
`PermissionError` controls. The host OCR tool itself is not the isolated agent.
No cross-platform, total-memory-limit or hosted-provider boundary is claimed.

The disclosed legacy-form parser recognizes printed headers, item boundaries
and schema field labels. It accepts a label typo only when edit distance one
identifies one schema field unambiguously. It maps `O`, `I` and `l` in numeric
fields to `0`, `1` and `1`, following the published numeric OCR convention.
It does not repair lot or document identifiers from task-specific expectations.
The existing public reconciliation algorithm computes payment/release decisions
from these observed records. Missing or ambiguous extraction remains a failure.

Only after the isolated policy replies does the evaluator consult canonical
source text for OCR metrics and the original business/evidence grader. Page
provenance, payload, policy response, raw OCR and business diagnostics are all
retained. A wrong ordered quantity and absent read-page evidence must fail strict
success for every emitted answer.

## Reproduce and audit

Use fresh output paths and the existing unchanged scan corpus:

```sh
python scripts/qualify_scan_agent.py \
  --corpus output/pdf/supplier-scans-v2 \
  --run-dir runs/scan-agent-new --report reports/scan-agent-new.json --workers 2
python scripts/audit_scan_agent.py check --report reports/scan-agent-new.json \
  --output reports/scan-agent-new-audit.json
python scripts/audit_scan_agent.py replay --report reports/scan-agent-new.json \
  --output reports/scan-agent-new-replay.json
python scripts/check_scan_audit_controls.py --report reports/scan-agent-new.json \
  --output reports/scan-agent-new-audit-controls.json
```

Qualification runs fresh OCR for every page and fresh isolated response replay
for every presentation, including failed ones. The separate replay command
retains per-case payload and recorded/fresh response hashes. It reruns the
isolated policy on retained OCR observations; it does **not** rerun OCR.

The read-only auditor reconstructs each policy payload from its public OCR text,
checks exact page and receipt coverage, recomputes OCR metrics, regrades retained
answers and exercises no-read controls. It does not authenticate a malicious
author's claimed OCR execution or confer independent review. Six additional
negative controls try forged summary counts, duplicate cases, reference-answer
payload injection, changed token metrics, changed business scores and a false
private-path probe verdict. They use temporary copies without altering original
evidence.

For the archived first control, add
`--source-snapshot runs/scan-agent-v1/implementation-snapshot` to the auditor.
Its result explicitly reports archived sources rather than current-source
qualification.
