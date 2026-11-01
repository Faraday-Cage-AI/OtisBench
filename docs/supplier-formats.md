# Synthetic supplier-format extension

This separate extension adds **48 matched presentations of 16 existing procurement
scenarios**: 8 reconciliation contracts × 2 authored variations × 3 layouts. It
adds **zero native business cases**, and does not create a tenth native track.

The layouts use visibly different page structures and field vocabulary:

- Landscape supplier tables: one heading per column, then rows of values.
- Portrait vendor cards: pairs of labeled fields, reordered within each item.
- Monospaced legacy statements: aligned abbreviated labels and equals-delimited values.

`Qty`, `Units / UOM`, `Price / UOM USD`, `Material lot`, `Expiry date` and similar
visible labels replace the canonical form's vocabulary. Forms include RFQ and PO
revisions, ACKs, packing, repeated POD events, certificates, deviations, logistics,
invoices/copies and credits. Every form remains explicitly synthetic. These are
clean searchable PDFs, not authentic supplier formats, scans or new transaction
semantics. Pagination remains four records per page so canonical page citations
remain valid. This intentionally limits the pagination-generalization claim.

## Qualification and scope

The generated corpus contains **726 PDFs / 786 pages**. Qualification extracts PDF
text, parses the disclosed layout, and checks that all **19,260 header/record fields**
match their original source values and that line-to-page evidence stays correct.
The check is evaluator-side; generated records do not enter the public parser.

A separate author control receives only public PDFs, their hashes and layout
metadata. It parses printed fields and calls the existing public-form
reconciliation policy. It does not import the reference solver. All 48
presentations must strictly pass the canonical fact-and-page-evidence grader.
For each answer, a changed ordered quantity must fail strict success. Receipts
retain answers, actual read pages, source PDF hashes, grading diagnostics and
corrupted-answer outcomes. This is author qualification, not model performance,
a new independent solver, a holdout, or practitioner validation. Exact receipt
regrading is an integrity check; it is not a new extraction run.

The generated PDFs expose ordinary visible text only: no hidden source records,
answers, target assessments, private invoice decisions, attachments or scripts
are added. The public packet manifests contain file hashes and source commitments,
not decoded records. This is a format-variation development set. A disclosed
layout parser doing well on it is not evidence of arbitrary supplier-format skill.

## Reproduce

Install the declared document extras and use a fresh output directory:

```sh
python -m pip install -e '.[dev,documents]'
python scripts/build_manifest.py
python scripts/document_formats.py build --output output/pdf/supplier-formats-v1
python scripts/document_formats.py qualify \
  --input output/pdf/supplier-formats-v1 \
  --report reports/document-formats-qualification.json
python scripts/document_formats.py check \
  --input output/pdf/supplier-formats-v1 \
  --report reports/document-formats-qualification.json
python scripts/document_formats.py examples \
  --input output/pdf/supplier-formats-v1 \
  --output output/pdf/supplier-layout-examples.pdf
```

`build` refuses to overwrite an existing corpus. `qualify` reruns extraction,
source-fact comparison, public reconciliation and answer corruption controls;
it writes local receipts under `runs/document-formats-qualification/`.
`check` is read-only and verifies source/file commitments, receipt coverage and
regrades retained answers. It cannot substitute for extraction qualification.
Retain the generated corpus and local receipts with the report. Their contents
are not bundled into the installable native-track wheel.
