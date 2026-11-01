# Procurement PDF and image-document reconciliation

This native assessment track has **32 packets**: eight disruption contracts,
two authored business variations per contract, and two matched evidence modes.
There are **16 underlying commercial scenarios**. Each is supplied once as
searchable PDFs and once as actual image-only PDFs.

The corpus contains 484 PDF files and 524 pages across matched modes. Forms include
released/old/draft RFQs, PO amendments, supplier acknowledgments, packing lists,
duplicate carrier PODs, lot certificates, scoped deviations, shipment clearances,
invoices, duplicate invoice copies, draft corrections and credit notes. The authored forms have matched text and raster evidence.

## Work and evidence

An agent reconciles four lines per packet, returning ordered, physically delivered,
accepted and missing EA quantities; supported payable and net invoice cents;
payment recommendations; released/quarantined lot quantities; hold reasons; and
page citations grouped by purchase, receiving, quality and invoice evidence.
A carrier delivery to another plant is different from stock physically received
but blocked by a shipment hold. A grade waiver has a quantity cap, lot/PO scope
and an expiry date. Invoice copies do not create extra liabilities, and an old
or draft document cannot replace the effective released revision.

| Contract | Required distinction |
|---|---|
| Revision effectivity | Released RFQ drawing vs stale supplier acknowledgment; a newer draft does not govern |
| Receiving units | BOX/CASE/EA conversion, a short receipt, and a mismatched certificate variation |
| Split delivery | Received vs in-transit shipments; repeated POD copies do not create inventory |
| Supplier deviation | Released/current/capped waiver vs expired or draft waiver |
| Invoice matching | Net billed amount vs supported liability at the effective PO rate |
| Duplicate liability | Identical invoice business ID/revision copies are alternatives, not additive bills |
| Cross-shipment | Carrier delivery elsewhere does not establish receipt at the intended plant |
| Shipment clearance | Physical arrival does not establish the required release status |

All policy, status/effectivity rules, quantities, prices and citation requirements
are explicit public inputs. Shipment-clearance rules are specified in each task policy.

This is a document assessment track. Recommendations do not execute a PO,
release actual inventory or transfer money. Use the separate coupled procurement
track to evaluate persisted operational actions and financial/physical state.

## Native source tools

The startup supplies a neutral task, public policy, answer schema and tools. It
excludes the private disruption label, seeds, generated source tables, reference
answers and expected citations. `list_documents` supplies business titles, hashes
and page counts. `read_page` returns an actual PDF text layer, OCR of the frozen
page image, or PNG bytes. Image-only PDFs have no extractable page text: the
baseline must request OCR. Neither extraction tool chooses effective documents,
converts business units or computes a reconciliation for the agent.

The extractor versions and source hashes are retained in traces. OCR uses the
installed Tesseract English model and a bounded subprocess timeout. Frozen PDFs
and PNGs are hashed and included in the source distribution. Replaying under a
changed OCR engine that changes output correctly fails exact trace comparison.

## Scoring

Strict success requires exact line coverage, all numeric/boolean/lot/disposition
facts, and all four source-evidence groups for every line. Partial score is 70%
factual reconciliation and 30% evidence. Cited pages must actually have been read
in the tool episode. Purchase/receiving/quality groups require the corresponding
effective source pages. Invoice evidence allows either identical effective copy;
eligible credit pages are also required. Shotgun citations to draft, superseded,
unrelated or unissued pages cannot substitute for the required sources.

The grader permits incorrect assessments to be submitted; a successful `finish`
call is not business correctness. Schema errors, duplicate/missing lines and
invented source references cannot earn strict success. Scores stay separate from
workflow execution, CAD geometry and factory profit.

## Run, export and qualify

```bash
python -m pip install -e '.[dev,documents]'
# Install pdftoppm and Tesseract with its English language data on the host.
otisbench list --track documents
otisbench export-document-packet --task doc-split_delivery-02-image_pdf \
  --output-dir runs/packet
otisbench isolated --track documents --task doc-split_delivery-02-image_pdf \
  --agent-file examples/document_agent.py --output runs/documents.json
otisbench replay runs/documents.json
python scripts/qualify_documents.py
python scripts/build_manifest.py --check
python scripts/audit_release.py
```

`documents --agent-command ...` also supports an ordinary JSONL subprocess.
Only the explicit `isolated` command enforces the macOS boundary. The new document
qualification uses that boundary for the standalone public-form baseline. The
OCR/PDF tools execute in the evaluator and expose raw source content only.

Qualification checks all 32 public-page baseline episodes and exact replays,
reference/schema consistency, answer/evidence mutations on every line, no-read
controls, empty submissions, duplicate and missing lines. A separate regression
suite checks physical/economic distinctions and actual PDF text-layer absence.
These are author controls using clean synthetic forms and tool-assisted OCR;
they establish neither learned-model nor vision-model performance, independent
ground truth, real-data accuracy, private held-outs or practitioner validation.
