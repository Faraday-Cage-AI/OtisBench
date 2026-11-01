"""Synthetic supplier-layout extension; matched presentations, not new scenarios.

Public controls parse only PDF text and use the published reconciliation policy.
The evaluator separately checks source-fact preservation and canonical grading.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STYLES = ('supplier_table', 'vendor_cards', 'legacy_statement')
ALIASES = {'Line': 'Line #', 'Item': 'Part no.', 'Drawing': 'Drawing rev.', 'Quantity': 'Qty',
           'EA per UOM': 'Units / UOM', 'Price USD': 'Price / UOM USD', 'Lot': 'Material lot',
           'Damaged EA': 'Damaged units', 'Max EA': 'Maximum units', 'Valid through': 'Expiry date',
           'Amount USD': 'Credit USD', 'Release': 'Release state'}
REVERSE = {v: k for k, v in ALIASES.items()}
FIELDS = set('Line Item Drawing Grade Quantity UOM Shipment Lot Delivery Destination Clearance PO Invoice'.split()) | set(ALIASES)
LABELS = {ALIASES.get(k, k): k for k in FIELDS}


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def render(document, style):
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor
    if style not in STYLES: raise ValueError('unknown layout')
    landscape = style == 'supplier_table'
    width, height = (792, 612) if landscape else (612, 792)
    stream = BytesIO(); c = canvas.Canvas(stream, pagesize=(width, height), invariant=1, pageCompression=1)
    c.setTitle(document['title']); c.setAuthor('Faraday synthetic supplier-layout fixtures')
    records = document['records']; pages = max(1, (len(records) + 3) // 4)
    for page in range(pages):
        chunk = records[page * 4:(page + 1) * 4]
        c.setFillColor(HexColor('#172C40')); c.setFont('Helvetica-Bold', 18)
        c.drawString(36, height - 38, {'supplier_table': 'SUPPLIER OPERATIONS', 'vendor_cards': 'VENDOR RECORD', 'legacy_statement': 'MATERIAL CONTROL STATEMENT'}[style])
        c.setFont('Helvetica', 10); c.drawString(36, height - 57, document['title'])
        c.setFont('Helvetica', 9); c.drawString(36, height - 72, 'SYNTHETIC EVALUATION FIXTURE')
        # The order in the text layer follows visible reading order; no hidden fields.
        for i, (key, value) in enumerate(document['headers'].items()):
            col, row = i % 2, i // 2
            c.drawString(36 + col * (width - 72) / 2, height - 96 - row * 15, f'{key}: {value}')
        top = height - 157
        c.setFont('Helvetica-Bold', 10); c.drawString(36, top, 'LINE ITEMS'); top -= 22
        if style == 'supplier_table':
            keys = sorted(chunk[0]) if chunk else []
            if any(set(record) != set(keys) for record in chunk): raise ValueError('heterogeneous table fields')
            cell = (width - 72) / max(1, len(keys))
            c.setFillColor(HexColor('#EAF0F4')); c.rect(35, top - 7, width - 70, 23, fill=1, stroke=0)
            c.setFillColor(HexColor('#172C40')); c.setFont('Helvetica-Bold', 7.7)
            for j, key in enumerate(keys):
                label = ALIASES.get(key, key)
                if c.stringWidth(label, 'Helvetica-Bold', 7.7) > cell - 7: raise ValueError('table label too wide')
                c.drawString(39 + j * cell, top, label)
            top -= 28
            for row, record in enumerate(chunk):
                if row % 2 == 0:
                    c.setFillColor(HexColor('#F4F6F8')); c.rect(35, top - 8, width - 70, 22, fill=1, stroke=0)
                c.setFillColor(HexColor('#172C40')); c.setFont('Helvetica', 9)
                for j, key in enumerate(keys):
                    value = str(record[key])
                    if c.stringWidth(value, 'Helvetica', 9) > cell - 7: raise ValueError('table value too wide')
                    c.drawString(39 + j * cell, top, value)
                top -= 25
        else:
            for j, record in enumerate(chunk, page * 4 + 1):
                keys = list(reversed(record)) if style == 'vendor_cards' else sorted(record)
                c.setFont('Helvetica-Bold' if style == 'vendor_cards' else 'Courier-Bold', 9)
                c.drawString(36, top, f'ITEM {j}'); top -= 16
                if style == 'vendor_cards':
                    start = top
                    for i, key in enumerate(keys):
                        col, row = i % 2, i // 2
                        c.setFont('Helvetica', 9)
                        label = f'{ALIASES.get(key, key)}: {record[key]}'
                        if c.stringWidth(label, 'Helvetica', 9) > 260: raise ValueError('card field too wide')
                        c.drawString(43 + col * 270, start - row * 15, label)
                    top = start - ((len(keys) + 1) // 2) * 15 - 13
                else:
                    c.setFont('Courier', 9)
                    for key in keys:
                        text = f'{ALIASES.get(key, key):<20} = {record[key]}'
                        if c.stringWidth(text, 'Courier', 9) > width - 80: raise ValueError('statement field too wide')
                        c.drawString(42, top, text); top -= 12
                    top -= 8
                c.setStrokeColor(HexColor('#C8D0D8')); c.line(36, top + 9, width - 36, top + 9)
        if top < 63: raise ValueError('layout exceeds printable page')
        c.setFont('Helvetica', 8); c.drawString(36, top - 14, 'END OF ITEMS')
        c.setFont('Helvetica', 8); c.drawString(36, 25, 'Synthetic data - not an order, certificate or payment instruction.')
        c.drawRightString(width - 36, 25, f'{document["id"]} / Page {page + 1} of {pages}')
        c.showPage()
    c.save(); return stream.getvalue()


def parse_page(text, style, page):
    """Disclosed-format text parser. Never receives generated records or references."""
    if style not in STYLES: raise ValueError('unknown layout')
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    if lines.count('LINE ITEMS') != 1 or lines.count('END OF ITEMS') != 1: raise ValueError('missing form boundaries')
    start, end = lines.index('LINE ITEMS'), lines.index('END OF ITEMS')
    if end < start: raise ValueError('reversed form boundaries')
    header = {}
    for line in lines[:start]:
        if ':' in line:
            key, value = line.split(':', 1)
            if key in header: raise ValueError('duplicate header')
            header[key] = value.strip()
    if set(header) != {'Form', 'Business', 'Revision', 'Status', 'PO', 'As of'}: raise ValueError('missing public header')
    body = lines[start + 1:end]; records = []
    if style == 'supplier_table':
        n = 0
        while n < len(body) and body[n] in LABELS: n += 1
        keys = [LABELS[label] for label in body[:n]]
        if not keys or len(set(keys)) != n or (len(body) - n) % n: raise ValueError('invalid table shape')
        for offset in range(n, len(body), n):
            records.append(dict(zip(keys, body[offset:offset + n])))
    else:
        current = None
        for line in body:
            if re.fullmatch(r'ITEM [1-9][0-9]*', line):
                current = {}; records.append(current); continue
            separator = ':' if style == 'vendor_cards' else '='
            if current is None or separator not in line: raise ValueError('invalid item field')
            label, value = line.split(separator, 1); key = LABELS.get(label.strip())
            if key is None or key in current: raise ValueError('unknown or duplicate field')
            current[key] = value.strip()
    if not records or any(not r or 'Line' not in r for r in records): raise ValueError('missing line records')
    return header, records


def extract(path, style):
    from pypdf import PdfReader
    header, records = {}, []
    reader = PdfReader(path)
    for page, pdf_page in enumerate(reader.pages, 1):
        current, rows = parse_page(pdf_page.extract_text(), style, page)
        if header and header != current: raise ValueError('conflicting page header')
        header = current
        records.extend(dict(r, _page=page) for r in rows)
    return dict(header=header, records=records, pages=len(reader.pages))


def baseline(packet):
    """Only public PDFs/index enter the public-form reconciliation control."""
    packet = Path(packet); task = json.loads((packet / 'task.json').read_text()); source = []
    spec = importlib.util.spec_from_file_location('public_document_control', ROOT / 'examples/document_agent.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    for document in task['documents']:
        path = packet / document['filename']
        if sha(path) != document['sha256']: raise ValueError('PDF hash mismatch')
        parsed = extract(path, task['layout'])
        if parsed['pages'] != document['pages']: raise ValueError('page inventory mismatch')
        source.append(dict(id=document['id'], header={module.key(k): v for k, v in parsed['header'].items()},
            records=[{module.key(k) if k != '_page' else k: v for k, v in r.items()} for r in parsed['records']]))
    return module.reconcile(source)


def build(destination):
    from faraday_manufacturing_benchmark.document_cases import catalog, build as source_build
    from faraday_manufacturing_benchmark.documents import public_task
    destination = Path(destination)
    if destination.exists(): raise ValueError('destination already exists')
    destination.mkdir(parents=True); entries = []
    tasks = [t for t in catalog() if t['mode'] == 'searchable_pdf']
    for task in tasks:
        source = source_build(task)
        for style in STYLES:
            name = task['id'].replace('-searchable_pdf', '') + '-' + style
            packet = destination / name; packet.mkdir(); docs = []
            for document in source['documents']:
                path = packet / (document['id'] + '.pdf'); path.write_bytes(render(document, style))
                docs.append(dict(id=document['id'], filename=path.name, title=document['title'], pages=max(1, (len(document['records']) + 3) // 4), sha256=sha(path)))
            save(packet / 'task.json', dict(task=public_task(task), layout=style, documents=docs))
            entries.append(dict(packet=name, evaluator_task_id=task['id'], layout=style, source_facts_sha256=digest(source)))
    (destination / 'DATA_LICENSE').write_text((ROOT / 'DATA_LICENSE').read_text())
    (destination / 'README.md').write_text((ROOT / 'docs/supplier-formats.md').read_text())
    save(destination / 'manifest.json', dict(protocol='synthetic-supplier-formats/1', underlying_scenarios=len(tasks),
        presentations=len(entries), native_case_count_added=0, layouts=list(STYLES),
        data_license='CC-BY-4.0', attribution='Faraday Manufacturing Benchmark contributors; synthetic supplier-format extension.',
        generator_sha256=sha(__file__), release_manifest_sha256=sha(ROOT / 'manifest.json'), cases=entries,
        files={p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob('*')) if p.is_file()},
        limitations=['Synthetic clean searchable PDFs only; no authentic supplier forms or degraded scans.',
                     'Matched presentations of the same 16 development scenarios; not distinct business cases.',
                     'Author public-form control, not a learned-model result, holdout or independent validation.']))
    return len(entries)


def qualify(destination, report_path):
    import pypdf, reportlab
    from faraday_manufacturing_benchmark.document_cases import catalog, build as source_build
    from faraday_manufacturing_benchmark.documents import grade
    destination = Path(destination); manifest = json.loads((destination / 'manifest.json').read_text())
    if manifest['generator_sha256'] != sha(__file__): raise ValueError('format generator changed')
    actual = {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()} - {'manifest.json'}
    if actual != set(manifest['files']): raise ValueError('file inventory mismatch')
    for name, expected in manifest['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or destination.joinpath(path).is_symlink(): raise ValueError('unsafe packet path')
        if sha(destination / path) != expected: raise ValueError('source hash mismatch')
    tasks = {t['id']: t for t in catalog() if t['mode'] == 'searchable_pdf'}
    expected_cases = {(key, style) for key in tasks for style in STYLES}
    observed_cases = [(e['evaluator_task_id'], e['layout']) for e in manifest['cases']]
    if len(observed_cases) != len(expected_cases) or set(observed_cases) != expected_cases:
        raise ValueError('missing, extra or duplicate presentation coverage')
    cases = []; docs_total = pages_total = fields_total = 0; matched_answers = {}
    receipt_root = ROOT / 'runs' / Path(report_path).stem
    receipt_root.mkdir(parents=True, exist_ok=True)
    for entry in manifest['cases']:
        task = tasks[entry['evaluator_task_id']]; source = source_build(task); packet = destination / entry['packet']
        expected_packet = task['id'].replace('-searchable_pdf', '') + '-' + entry['layout']
        if entry['packet'] != expected_packet: raise ValueError('unexpected packet path')
        if entry['source_facts_sha256'] != digest(source): raise ValueError('canonical facts changed')
        meta = json.loads((packet / 'task.json').read_text()); read_pages = set()
        if meta['layout'] != entry['layout']: raise ValueError('layout contract mismatch')
        for document, exported in zip(source['documents'], meta['documents'], strict=True):
            if exported['id'] != document['id'] or exported['filename'] != document['id'] + '.pdf':
                raise ValueError('document identity mismatch')
            parsed = extract(packet / exported['filename'], entry['layout'])
            reconstructed = [dict((k, v) for k, v in r.items() if k != '_page') for r in parsed['records']]
            if parsed['header'] != document['headers'] or reconstructed != document['records']: raise ValueError('PDF lost or changed a source fact')
            for i, record in enumerate(parsed['records']):
                if record['_page'] != 1 + i // 4: raise ValueError('page citation location changed')
            read_pages.update((document['id'], p) for p in range(1, parsed['pages'] + 1))
            docs_total += 1; pages_total += parsed['pages']; fields_total += len(parsed['header']) + sum(len(r) for r in reconstructed)
        answer = baseline(packet); result = grade(task, answer, read_pages)
        if not result['strict_success']: raise ValueError('public-only form control failed: ' + entry['packet'])
        previous = matched_answers.setdefault(task['id'], digest(answer))
        if previous != digest(answer): raise ValueError('matched layouts produced different control answers')
        wrong = deepcopy(answer); wrong['lines'][0]['ordered_ea'] += 1
        negative = grade(task, wrong, read_pages)
        if negative['strict_success']: raise ValueError('corrupted answer accepted')
        receipt = receipt_root / (entry['packet'] + '.json')
        save(receipt, dict(packet=entry['packet'], extension_manifest_sha256=sha(destination / 'manifest.json'),
            public_document_hashes={d['filename']: d['sha256'] for d in meta['documents']},
            read_pages=[dict(document_id=k, page=p) for k, p in sorted(read_pages)],
            answer=answer, result=result, corrupted_answer=wrong, corrupted_result=negative))
        cases.append(dict(packet=entry['packet'], layout=entry['layout'], score=result['score'],
            strict_success=result['strict_success'], answer_sha256=digest(answer),
            corrupted_answer_rejected=not negative['strict_success'],
            receipt=str(receipt.relative_to(ROOT)), receipt_sha256=sha(receipt)))
    report = dict(protocol=manifest['protocol'], extension_manifest_sha256=sha(destination / 'manifest.json'),
        extraction_environment=dict(pypdf=pypdf.__version__, reportlab=reportlab.Version),
        source_sha256={str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), ROOT / 'examples/document_agent.py', ROOT / 'src/faraday_manufacturing_benchmark/document_cases.py', ROOT / 'src/faraday_manufacturing_benchmark/documents.py']},
        underlying_scenarios=manifest['underlying_scenarios'], native_case_count_added=0, presentations=len(cases),
        pdf_files=docs_total, pdf_pages=pages_total, source_fields_round_tripped=fields_total, cases=cases,
        qualification_passed=True, corrupted_answers_rejected=len(cases), matched_scenario_answers=len(matched_answers),
        control='Author disclosed-format PDF parser plus public reconciliation policy; no model or independent review.',
        scope=manifest['limitations'])
    save(report_path, report); return report


def check(destination, report_path):
    """Read-only source/PDF/receipt audit; does not rerun extraction or prove review."""
    from faraday_manufacturing_benchmark.document_cases import catalog
    from faraday_manufacturing_benchmark.documents import grade
    destination = Path(destination); report = json.loads(Path(report_path).read_text())
    manifest = json.loads((destination / 'manifest.json').read_text())
    if report['extension_manifest_sha256'] != sha(destination / 'manifest.json'):
        raise ValueError('extension manifest commitment changed')
    for name, expected in report['source_sha256'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or sha(path) != expected: raise ValueError('qualification source changed')
    actual = {p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()} - {'manifest.json'}
    if actual != set(manifest['files']): raise ValueError('public file inventory changed')
    for name, expected in manifest['files'].items():
        path = (destination / name).resolve()
        if not path.is_relative_to(destination.resolve()) or sha(path) != expected: raise ValueError('public source changed')
    expected = {e['packet']: e for e in manifest['cases']}
    if len(report['cases']) != len(expected) or {c['packet'] for c in report['cases']} != set(expected):
        raise ValueError('receipt case coverage mismatch')
    tasks = {t['id']: t for t in catalog()}
    for row in report['cases']:
        path = (ROOT / row['receipt']).resolve()
        if not path.is_relative_to(ROOT) or sha(path) != row['receipt_sha256']: raise ValueError('receipt changed')
        receipt = json.loads(path.read_text())
        if receipt['extension_manifest_sha256'] != report['extension_manifest_sha256'] or receipt['packet'] != row['packet']:
            raise ValueError('receipt provenance mismatch')
        task = tasks[expected[row['packet']]['evaluator_task_id']]
        pages = {(r['document_id'], r['page']) for r in receipt['read_pages']}
        for answer_key, result_key in [('answer', 'result'), ('corrupted_answer', 'corrupted_result')]:
            if grade(task, receipt[answer_key], pages) != receipt[result_key]: raise ValueError('grading receipt mismatch')
        if not receipt['result']['strict_success'] or receipt['corrupted_result']['strict_success']:
            raise ValueError('qualification controls failed')
    return dict(integrity_passed=True, presentations=len(expected), scope='Current-source PDF and receipt integrity; no new extraction, model run or independent review.')


def examples(destination, output):
    from pypdf import PdfWriter
    destination = Path(destination); writer = PdfWriter()
    for style in STYLES:
        packet = destination / ('doc-split_delivery-01-' + style)
        meta = json.loads((packet / 'task.json').read_text())
        for form, revision in [('PO', 2), ('PACKING', 1)]:
            doc = next(d for d in meta['documents'] if d['title'].startswith(form + ' ') and d['title'].endswith('/ rev ' + str(revision)))
            path = packet / doc['filename']
            if sha(path) != doc['sha256']: raise ValueError('example PDF source changed')
            writer.append(path, outline_item=style + ' / ' + form)
    writer.add_metadata({'/Title': 'Synthetic supplier layouts - matched PO and packing examples', '/Author': 'Faraday Manufacturing Benchmark'})
    Path(output).parent.mkdir(parents=True, exist_ok=True); writer.write(output)
    return dict(pages=len(writer.pages), sha256=sha(output))


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build'); create.add_argument('--output', required=True)
    qualification = sub.add_parser('qualify'); qualification.add_argument('--input', required=True); qualification.add_argument('--report', required=True)
    audit = sub.add_parser('check'); audit.add_argument('--input', required=True); audit.add_argument('--report', required=True)
    sample = sub.add_parser('examples'); sample.add_argument('--input', required=True); sample.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'build': print('Prepared presentations:', build(args.output))
    elif args.command == 'qualify':
        result = qualify(args.input, args.report)
        print(json.dumps({k: result[k] for k in ('qualification_passed', 'presentations', 'underlying_scenarios', 'pdf_files', 'pdf_pages', 'source_fields_round_tripped')}))
    elif args.command == 'examples': print(json.dumps(examples(args.input, args.output)))
    else: print(json.dumps(check(args.input, args.report)))


if __name__ == '__main__': main()
