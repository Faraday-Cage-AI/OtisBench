import importlib.util
from io import BytesIO
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from pypdf import PdfReader
from faraday_manufacturing_benchmark.document_cases import catalog,build
from faraday_manufacturing_benchmark.documents import grade
ROOT=Path(__file__).resolve().parents[1]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


agent=module('scan_policy','examples/supplier_scan_agent.py')
formats=module('scan_test_formats','scripts/document_formats.py')
ocr=module('scan_public_ocr','scripts/scan_ocr_tools.py')


@pytest.mark.parametrize('label,expected',[('Oty','quantity'),('uUOM','uom'),('Price / UOM USD','priceusd'),('Line #','line')])
def test_public_label_repairs_are_schema_only(label,expected):
    assert agent.field_label(label)==expected


def test_unknown_field_is_not_silently_discarded():
    with pytest.raises(ValueError):agent.field_label('Bank account')


@pytest.mark.parametrize('task',[t for t in catalog() if t['mode']=='searchable_pdf'],ids=lambda t:t['id'])
def test_public_printed_forms_parse_and_reconcile_before_ocr(task):
    source=build(task);payload={'documents':[]};read=set()
    for doc in source['documents']:
        reader=PdfReader(BytesIO(formats.render(doc,'legacy_statement')))
        pages=[dict(page=i,text=p.extract_text()) for i,p in enumerate(reader.pages,1)]
        payload['documents'].append(dict(id=doc['id'],pages=pages));read.update((doc['id'],p['page']) for p in pages)
    answer=agent.decide(payload)
    assert grade(task,answer,read)['strict_success']


def test_skew_estimate_comes_from_pixels():
    image=Image.new('L',(1000,1300),255);draw=ImageDraw.Draw(image)
    for y in range(250,1100,40):draw.rectangle((80,y,900,y+3),fill=20)
    tilted=image.rotate(1.,Image.Resampling.BICUBIC,fillcolor=255)
    assert abs(ocr.estimate_skew(tilted)+1.)<=.25
    assert ocr.estimate_skew(image)==0


def test_identifier_text_is_not_repaired_using_line_number():
    text='Form: PO Business: PO-1\nRevision: 1 Status: RELEASED\nPO: PO-1 As of: 2026-10-31\nLINE ITEMS\nITEM 1.\nLine # = l\nMaterial lot = LOT-l\nEND OF ITEMS'
    header,rows=agent.parse_scan(text,1)
    assert rows[0]['line']=='1'
    assert rows[0]['lot']=='LOT-l'
