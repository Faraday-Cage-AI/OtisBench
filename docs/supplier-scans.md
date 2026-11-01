# Supplier scan robustness

16 procurement document scenarios × 3 capture profiles produce 48 matched presentations.

The full corpus has 726 image-only PDFs / 786 raster pages. Every PDF is rebuilt
from visible page pixels and checked to have no selectable text. Public task
indexes contain document/page hashes, capture labels, and the ordinary public
answer schema. They contain no decoded source records, answers or decisions.

## Capture contracts

| Profile | Rendering and degradation |
|---|---|
| `raster_control` | 150 dpi, grayscale, lossless PNG; control for rasterization itself |
| `photocopy` | 120 dpi, contrast factor 0.72, Gaussian blur radius 0.45 pixels, seeded dark speckles on 0.03 percent of pixels, JPEG quality 45 |
| `skewed_capture` | 150 dpi, one-degree rotation inside the unchanged canvas, Gaussian blur radius 0.25 pixels, horizontal illumination ramp 0.76–1.0, JPEG quality 60 |

The original margins keep the small rotation away from printed content. These
are controlled synthetic perturbations, not photographs of authentic supplier
paperwork. Text is intentionally legible to a human. No perspective warp,
occlusion, handwriting, stamps, arbitrary supplier layouts or real camera
calibration is established. The supplied raster captures are fixed artifacts;
Poppler, Pillow and JPEG differences can change a newly generated corpus.

## Evaluation

The evaluator runs Tesseract 5 using English, page segmentation mode 6, and one
OpenMP thread per worker. Only the public PNG enters each OCR invocation. All OCR
stdout/stderr, return codes, page provenance and elapsed times are retained.
No private fact is inserted into OCR text or used to repair its mistakes.

Two separate outcomes are reported:

1. **OCR token recall and precision:** case-insensitive token multisets preserve
   decimal punctuation, identifiers and repeated-value counts. A missed or
   changed number reduces recovery. These metrics deliberately ignore reading
   order and row association. They are insufficient to establish document
   understanding or payment correctness. Headings and footers also contribute.
2. **Strict business reconciliation:** a disclosed legacy-layout parser splits
   the visible two-column header, parses printed records, and invokes the same
   public reconciliation policy as the clean supplier-format extension. The
   original canonical business-and-page-evidence grader evaluates the answer.
   Any extraction/reconciliation failure scores zero and remains in the report.
   This is a brittle author control, not an LLM or arbitrary-layout baseline.

The report records every case, including failures. Evaluation completion means
all presentations were attempted; it does not mean the control passed all cases.
The read-only `check` command verifies corpus and implementation commitments,
receipt/page coverage, recalculates metrics from retained OCR text, and regrades
retained answers. It does not rerun OCR or certify independent validation.

All capture profiles, layouts, PDF modes and other presentations of one source
scenario must stay in the **same partition**. Training on a clean presentation
and reporting its degraded twin as a held-out business problem is leakage.
This public development extension creates no secret or structurally new holdout.

## Reproduce

Use the existing document/Pillow/NumPy dependencies, Poppler and Tesseract. Run
from the benchmark root, with a fresh corpus and receipt directory:

```sh
python scripts/supplier_scans.py build --output output/pdf/supplier-scans-new
python scripts/supplier_scans.py qualify \
  --input output/pdf/supplier-scans-new \
  --run-dir runs/supplier-scans-new \
  --report reports/supplier-scans-new.json --workers 2
python scripts/supplier_scans.py check \
  --input output/pdf/supplier-scans-new \
  --report reports/supplier-scans-new.json
```

Build refuses existing output and less than 2 GiB free. Qualification refuses to
overwrite receipts. Worker count is bounded to 1–4. Preserve corpus, manifest,
receipts and source hashes together. The generated extension is separate from
the installable nine-track native wheel.
