from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
from faraday_manufacturing_benchmark.document_cases import catalog, build

spec = importlib.util.spec_from_file_location('document_formats', Path(__file__).resolve().parents[1] / 'scripts/document_formats.py')
formats = importlib.util.module_from_spec(spec); spec.loader.exec_module(formats)


@pytest.mark.parametrize('style', formats.STYLES)
@pytest.mark.parametrize('role', ['po', 'packing', 'pod', 'deviation', 'credits'])
def test_pdf_roundtrip_retains_all_fields_and_line_page_locations(tmp_path, style, role):
    task = next(t for t in catalog() if t['family'] == 'split_delivery')
    doc = next(d for d in build(task)['documents'] if d['role'] == role)
    path = tmp_path / 'supplier.pdf'; path.write_bytes(formats.render(doc, style))
    parsed = formats.extract(path, style)
    assert parsed['header'] == doc['headers']
    assert [{k: v for k, v in r.items() if k != '_page'} for r in parsed['records']] == doc['records']
    assert [r['_page'] for r in parsed['records']] == [1 + i // 4 for i in range(len(doc['records']))]
    assert path.read_bytes() == formats.render(doc, style)


def test_table_missing_value_and_duplicate_columns_are_rejected():
    header = '\n'.join(f'{k}: {v}' for k, v in {'Form': 'PO', 'Business': 'PO-1', 'Revision': '2', 'Status': 'RELEASED', 'PO': 'PO-1', 'As of': '2026-10-31'}.items())
    for rows in ['Line #\nQty\n1', 'Line #\nLine #\n1\n1']:
        with pytest.raises(ValueError): formats.parse_page(header + '\nLINE ITEMS\n' + rows + '\nEND OF ITEMS', 'supplier_table', 1)


@pytest.mark.parametrize('style,separator', [('vendor_cards', ':'), ('legacy_statement', '=')])
def test_duplicate_business_fields_are_rejected(style, separator):
    header = '\n'.join(f'{k}: x' for k in ('Form', 'Business', 'Revision', 'Status', 'PO', 'As of'))
    text = f'{header}\nLINE ITEMS\nITEM 1\nLine # {separator} 1\nQty {separator} 5\nQty {separator} 9\nEND OF ITEMS'
    with pytest.raises(ValueError, match='duplicate'): formats.parse_page(text, style, 1)


def test_unknown_layout_and_overflow_fail_before_pdf_is_published():
    doc = build(catalog()[0])['documents'][0]
    with pytest.raises(ValueError, match='unknown'): formats.render(doc, 'unregistered')
    bad = deepcopy(doc); bad['records'][0]['Item'] = 'X' * 300
    for style in formats.STYLES:
        with pytest.raises(ValueError, match='wide'): formats.render(bad, style)
