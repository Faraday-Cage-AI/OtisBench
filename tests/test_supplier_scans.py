from io import BytesIO
import importlib.util
from pathlib import Path
import pytest
from PIL import Image
from pypdf import PdfReader

spec = importlib.util.spec_from_file_location('supplier_scans', Path(__file__).resolve().parents[1] / 'scripts/supplier_scans.py')
scans = importlib.util.module_from_spec(spec); spec.loader.exec_module(scans)


@pytest.mark.parametrize('profile', scans.PROFILES)
def test_scan_preserves_full_canvas_is_deterministic_and_has_no_text_layer(profile):
    image = Image.new('L', (200, 260), 255)
    from PIL import ImageDraw
    ImageDraw.Draw(image).text((40, 100), 'Qty 14 / USD 12.50', fill=0)
    first = scans.degrade(image, profile, 175)
    assert first.size == image.size
    assert first.tobytes() == scans.degrade(image, profile, 175).tobytes()
    assert first.getextrema()[0] < first.getextrema()[1]
    pdf = scans.image_pdf([first], [(612, 792)])
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 1
    assert not reader.pages[0].extract_text().strip()
    assert len(reader.pages[0].images) == 1
    assert tuple(float(n) for n in reader.pages[0].mediabox[2:]) == (612., 792.)
    assert pdf == scans.image_pdf([first], [(612, 792)])


def test_corrupt_numbers_and_repeated_values_reduce_recall():
    result = scans.token_metrics('Qty 12 12 Price 1.20 Lot AB-12', 'Qty 12 Price 120 Lot AB-13')
    assert result['token_recall'] < 1
    assert not result['exact_token_multiset']
    assert scans.token_metrics('12 12', '12')['matched_tokens'] == 1
    assert scans.token_metrics('1.20', '120')['matched_tokens'] == 0


def test_metric_explicitly_ignores_reading_order():
    assert scans.token_metrics('Qty 12 Lot AB-12', 'Lot AB-12 Qty 12')['exact_token_multiset']


def test_empty_ocr_is_not_perfect():
    assert scans.token_metrics('Qty 12', '')['token_recall'] == 0
    assert scans.token_metrics('Qty 12', '')['token_precision'] == 0


def test_public_header_split_preserves_values():
    text = 'Form: PO Status: RELEASED\nBusiness: PO-123 PO: PO-123\nRevision: 2 As of: 2026-10-31'
    assert scans.prepare_ocr(text).splitlines() == ['Form: PO', 'Status: RELEASED', 'Business: PO-123', 'PO: PO-123', 'Revision: 2', 'As of: 2026-10-31']


def test_unknown_profile_rejected():
    with pytest.raises(ValueError): scans.degrade(Image.new('L', (2, 2)), 'invented', 1)
