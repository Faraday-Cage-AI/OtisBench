"""Matched synthetic scan robustness study; no new business cases or model scores."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import importlib.util
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scan_formats', ROOT / 'scripts/document_formats.py')
formats = importlib.util.module_from_spec(spec); spec.loader.exec_module(formats)
PROFILES = ('raster_control', 'photocopy', 'skewed_capture')
PROTOCOL = 'synthetic-supplier-scans/1'


def degrade(image, profile, seed):
    """Deterministic full-canvas transform. No source fields enter this function."""
    if profile not in PROFILES: raise ValueError('unknown scan profile')
    image = image.convert('L')
    if profile == 'raster_control': return image
    if profile == 'photocopy':
        image = ImageEnhance.Contrast(image).enhance(.72).filter(ImageFilter.GaussianBlur(.45))
        array = np.asarray(image).copy(); rng = np.random.default_rng(seed)
        mask = rng.random(array.shape) < .0003; array[mask] = 65
        image = Image.fromarray(array)
    else:
        image = image.rotate(1.0, Image.Resampling.BICUBIC, expand=False, fillcolor=255)
        image = image.filter(ImageFilter.GaussianBlur(.25))
        shade = np.linspace(.76, 1., image.width)
        image = Image.fromarray(np.clip(np.asarray(image) * shade[None, :], 0, 255).astype('uint8'))
    stream = BytesIO(); image.save(stream, 'JPEG', quality=45 if profile == 'photocopy' else 60)
    return Image.open(BytesIO(stream.getvalue())).convert('L')


def image_pdf(images, sizes):
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    stream = BytesIO(); c = canvas.Canvas(stream, invariant=1, pageCompression=1)
    c.setTitle('Synthetic supplier scan fixture'); c.setAuthor('Faraday Manufacturing Benchmark')
    for image, (width, height) in zip(images, sizes, strict=True):
        c.setPageSize((width, height)); c.drawImage(ImageReader(image), 0, 0, width=width, height=height)
        c.showPage()
    c.save(); return stream.getvalue()


def tokens(text):
    # Punctuation, decimals and identifiers remain distinct; repeated values count.
    return re.findall(r"[A-Za-z0-9]+(?:[./_-][A-Za-z0-9]+)*|[^\w\s]", text.casefold())


def token_metrics(expected, actual):
    target, observed = Counter(tokens(expected)), Counter(tokens(actual))
    matched = sum((target & observed).values()); n = sum(target.values()); m = sum(observed.values())
    return dict(expected_tokens=n, observed_tokens=m, matched_tokens=matched,
                token_recall=matched / n if n else 1., token_precision=matched / m if m else float(not n),
                exact_token_multiset=target == observed)


def prepare_ocr(text):
    """Split the disclosed two-column header; values never come from the source."""
    result = []
    for line in text.splitlines():
        parts = re.split(r'(?<!\S)(?=(?:Form|Business|Revision|Status|PO|As of):)', line)
        result.extend(part.strip() for part in parts if part.strip())
    return '\n'.join(result)


def source_tasks():
    from faraday_manufacturing_benchmark.document_cases import catalog
    return {t['id']: t for t in catalog() if t['mode'] == 'searchable_pdf'}


def build(output):
    import shutil
    from pypdf import PdfReader
    from faraday_manufacturing_benchmark.document_cases import build as source_build
    from faraday_manufacturing_benchmark.documents import public_task
    output = Path(output)
    if output.exists(): raise ValueError('destination already exists')
    if shutil.disk_usage(output.parent).free < 2 * 1024**3: raise ValueError('less than 2 GiB free; refusing scan build')
    output.mkdir(); entries = []
    with tempfile.TemporaryDirectory(prefix='supplier-scans-') as temporary:
        temp = Path(temporary)
        for task_id, task in source_tasks().items():
            source = source_build(task); per_profile = {p: [] for p in PROFILES}
            for document in source['documents']:
                pdf = formats.render(document, 'legacy_statement'); reader = PdfReader(BytesIO(pdf))
                clean = temp / 'source.pdf'; clean.write_bytes(pdf)
                for profile in PROFILES:
                    packet = output / (task_id.replace('-searchable_pdf', '') + '-' + profile)
                    packet.mkdir(exist_ok=True); images = []; sizes = []; pages = []
                    dpi = 120 if profile == 'photocopy' else 150
                    prefix = temp / 'page'
                    subprocess.run(['pdftoppm', '-r', str(dpi), '-gray', '-png', str(clean), str(prefix)], check=True, capture_output=True)
                    for index, page in enumerate(reader.pages, 1):
                        png = temp / f'page-{index}.png'
                        # Poppler zero-pads multi-page indices to the digit count of total pages.
                        if not png.exists(): png = temp / f'page-{index:0{len(str(len(reader.pages)))}}.png'
                        seed = int(formats.digest([task_id, document['id'], index, profile])[:16], 16)
                        with Image.open(png) as original: image = degrade(original, profile, seed)
                        path = packet / f'{document["id"]}-p{index}.png'; image.save(path, 'PNG')
                        images.append(image); sizes.append((float(page.mediabox.width), float(page.mediabox.height)))
                        pages.append(dict(page=index, filename=path.name, sha256=formats.sha(path), pixels=list(image.size)))
                    path = packet / f'{document["id"]}.pdf'; path.write_bytes(image_pdf(images, sizes))
                    if any(p.extract_text().strip() for p in PdfReader(path).pages): raise ValueError('unexpected PDF text layer')
                    per_profile[profile].append(dict(id=document['id'], filename=path.name, sha256=formats.sha(path),
                        pages=pages, clean_render_sha256=hashlib.sha256(pdf).hexdigest()))
            for profile, documents in per_profile.items():
                name = task_id.replace('-searchable_pdf', '') + '-' + profile
                packet = output / name
                formats.save(packet / 'task.json', dict(task=public_task(task), layout='legacy_statement', scan_profile=profile, documents=documents))
                entries.append(dict(packet=name, evaluator_task_id=task_id, profile=profile, source_facts_sha256=formats.digest(source)))
            print('built', task_id, flush=True)
    (output / 'DATA_LICENSE').write_text((ROOT / 'DATA_LICENSE').read_text())
    formats.save(output / 'manifest.json', dict(protocol=PROTOCOL, generator_sha256=formats.sha(__file__),
        underlying_scenarios=len(source_tasks()), presentations=len(entries), native_case_count_added=0,
        profiles=list(PROFILES), cases=entries, source_group_rule='All profiles/layouts of one source scenario stay in one partition.',
        files={p.relative_to(output).as_posix(): formats.sha(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    return dict(presentations=len(entries), underlying_scenarios=len(source_tasks()))


def validate_corpus(root):
    root = Path(root).resolve(); manifest = json.loads((root / 'manifest.json').read_text())
    if manifest['protocol'] != PROTOCOL or manifest['generator_sha256'] != formats.sha(__file__): raise ValueError('scan implementation changed')
    expected = {(t, p) for t in source_tasks() for p in PROFILES}
    observed = [(e['evaluator_task_id'], e['profile']) for e in manifest['cases']]
    if len(observed) != len(expected) or set(observed) != expected: raise ValueError('incomplete or duplicate scan coverage')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} - {'manifest.json'}
    if actual != set(manifest['files']): raise ValueError('scan file inventory changed')
    for name, expected_hash in manifest['files'].items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or formats.sha(path) != expected_hash: raise ValueError('scan file changed or unsafe path')
    return manifest


def public_ocr(packet, document, page):
    """OCR process sees only a public raster. No source facts or reference answers."""
    path = packet / page['filename']
    if formats.sha(path) != page['sha256']: raise ValueError('page hash mismatch')
    start = time.monotonic()
    result = subprocess.run(['tesseract', str(path), 'stdout', '--psm', '6', '-l', 'eng'],
                            capture_output=True, text=True, timeout=45, env={**__import__('os').environ, 'OMP_THREAD_LIMIT': '1'})
    return dict(document_id=document['id'], page=page['page'], source_sha256=page['sha256'],
                text=result.stdout, exit_code=result.returncode, stderr=result.stderr,
                elapsed_seconds=time.monotonic() - start)


def qualify(root, run_dir, report_path, workers=2):
    from pypdf import PdfReader
    from faraday_manufacturing_benchmark.document_cases import build as source_build
    from faraday_manufacturing_benchmark.documents import grade
    root = Path(root).resolve(); run_dir = Path(run_dir).resolve(); manifest = validate_corpus(root)
    if run_dir.exists(): raise ValueError('run directory already exists; preserve original receipts')
    run_dir.mkdir(parents=True); cases = []; tasks = source_tasks()
    spec = importlib.util.spec_from_file_location('scan_public_policy', ROOT / 'examples/document_agent.py')
    policy = importlib.util.module_from_spec(spec); spec.loader.exec_module(policy)
    sources = [Path(__file__), ROOT / 'scripts/document_formats.py', ROOT / 'examples/document_agent.py',
               ROOT / 'src/faraday_manufacturing_benchmark/document_cases.py', ROOT / 'src/faraday_manufacturing_benchmark/documents.py']
    source_hashes = {str(p.relative_to(ROOT)): formats.sha(p) for p in sources}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for entry in manifest['cases']:
            packet = root / entry['packet']; meta = json.loads((packet / 'task.json').read_text())
            task = tasks[entry['evaluator_task_id']]; source = source_build(task)
            if formats.digest(source) != entry['source_facts_sha256']: raise ValueError('source scenario changed')
            jobs = [(document, page) for document in meta['documents'] for page in document['pages']]
            ocr_rows = list(pool.map(lambda job: public_ocr(packet, *job), jobs)); parsed_docs = []; parser_error = None
            pages_read = {(r['document_id'], r['page']) for r in ocr_rows if r['exit_code'] == 0}
            metrics = []; lookup = {(r['document_id'], r['page']): r for r in ocr_rows}
            for document in source['documents']:
                clean = PdfReader(BytesIO(formats.render(document, 'legacy_statement')))
                parsed = dict(id=document['id'], header={}, records=[])
                for page, pdf_page in enumerate(clean.pages, 1):
                    row = lookup[document['id'], page]
                    metrics.append(dict(document_id=document['id'], page=page,
                                        **token_metrics(pdf_page.extract_text(), row['text'])))
                    try:
                        if row['exit_code'] != 0: raise ValueError('OCR process failed')
                        h, records = formats.parse_page(prepare_ocr(row['text']), 'legacy_statement', page)
                        if parsed['header'] and parsed['header'] != h: raise ValueError('conflicting public page headers')
                        parsed['header'] = h
                        parsed['records'].extend({**{policy.key(k): v for k, v in record.items()}, '_page': page} for record in records)
                    except (ValueError, KeyError) as error:
                        if parser_error is None: parser_error = type(error).__name__ + ': ' + str(error)
                parsed['header'] = {policy.key(k): v for k, v in parsed['header'].items()}; parsed_docs.append(parsed)
            answer = None; result = dict(score=0., strict_success=False, error_type='ExtractionFailed')
            if parser_error is None:
                try: answer = policy.reconcile(parsed_docs); result = grade(task, answer, pages_read)
                except (ValueError, KeyError, IndexError, ArithmeticError) as error: parser_error = type(error).__name__ + ': ' + str(error)
            n = sum(m['expected_tokens'] for m in metrics); m = sum(m['observed_tokens'] for m in metrics); matched = sum(m['matched_tokens'] for m in metrics)
            receipt = run_dir / (entry['packet'] + '.json')
            formats.save(receipt, dict(packet=entry['packet'], extension_manifest_sha256=formats.sha(root / 'manifest.json'),
                ocr=ocr_rows, metrics=metrics, parser_error=parser_error, answer=answer, result=result))
            cases.append(dict(packet=entry['packet'], profile=entry['profile'], pages=len(metrics),
                expected_tokens=n, observed_tokens=m, matched_tokens=matched, token_recall=matched/n, token_precision=matched/m if m else 0.,
                strict_success=result['strict_success'], score=result['score'], parser_error=parser_error,
                receipt=str(receipt.relative_to(ROOT)), receipt_sha256=formats.sha(receipt)))
            report = dict(protocol=PROTOCOL, status='running', extension_manifest_sha256=formats.sha(root / 'manifest.json'),
                source_sha256=source_hashes, tesseract=subprocess.run(['tesseract','--version'], capture_output=True,text=True,check=True).stdout.splitlines()[0],
                presentations_expected=len(manifest['cases']), presentations_resolved=len(cases), native_case_count_added=0,
                cases=cases, scope='Public Tesseract/disclosed-parser author control. Matched synthetic degradations, not authentic scans, independent review, model inference or a private holdout. Token metrics ignore reading order and row association.')
            formats.save(report_path, report)
            print(entry['packet'], 'recall', round(matched/n, 4), 'strict', result['strict_success'], flush=True)
    if source_hashes != {str(p.relative_to(ROOT)): formats.sha(p) for p in sources}: raise ValueError('source changed during qualification')
    report['status'] = 'complete'; report['profiles'] = {}
    for profile in PROFILES:
        rows = [r for r in cases if r['profile'] == profile]
        n = sum(r['expected_tokens'] for r in rows); m = sum(r['observed_tokens'] for r in rows); hit = sum(r['matched_tokens'] for r in rows)
        report['profiles'][profile] = dict(presentations=len(rows), pages=sum(r['pages'] for r in rows),
            token_recall=hit/n, token_precision=hit/m if m else 0., strict_successes=sum(r['strict_success'] for r in rows))
    formats.save(report_path, report); return report


def check(root, report_path):
    """Artifact/metric/grading integrity. Does not rerun OCR or imply success."""
    from pypdf import PdfReader
    from faraday_manufacturing_benchmark.document_cases import build as source_build
    from faraday_manufacturing_benchmark.documents import grade
    root = Path(root); manifest = validate_corpus(root); report = json.loads(Path(report_path).read_text())
    if report['extension_manifest_sha256'] != formats.sha(root / 'manifest.json'): raise ValueError('manifest commitment mismatch')
    if report['status'] != 'complete': raise ValueError('qualification incomplete')
    for name, expected in report['source_sha256'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or formats.sha(path) != expected: raise ValueError('qualification source changed')
    entries = {e['packet']: e for e in manifest['cases']}; tasks = source_tasks()
    if len(report['cases']) != len(entries) or {r['packet'] for r in report['cases']} != set(entries): raise ValueError('receipt coverage mismatch')
    totals = {p: dict(presentations=0, pages=0, expected_tokens=0, observed_tokens=0, matched_tokens=0, strict_successes=0) for p in PROFILES}
    for row in report['cases']:
        path = (ROOT / row['receipt']).resolve()
        if not path.is_relative_to(ROOT) or formats.sha(path) != row['receipt_sha256']: raise ValueError('receipt changed')
        receipt = json.loads(path.read_text()); entry = entries[row['packet']]
        if receipt['packet'] != row['packet'] or receipt['extension_manifest_sha256'] != report['extension_manifest_sha256']: raise ValueError('receipt provenance mismatch')
        if row['profile'] != entry['profile']: raise ValueError('profile mismatch')
        source = source_build(tasks[entry['evaluator_task_id']]); packet = root / entry['packet']
        meta = json.loads((packet / 'task.json').read_text())
        expected_pages = {(d['id'], p['page']): p for d in meta['documents'] for p in d['pages']}
        observed = {(r['document_id'], r['page']): r for r in receipt['ocr']}
        if len(observed) != len(receipt['ocr']) or set(observed) != set(expected_pages): raise ValueError('OCR page coverage mismatch')
        expected_metrics = []
        for document in source['documents']:
            clean = PdfReader(BytesIO(formats.render(document, 'legacy_statement')))
            for page, pdf_page in enumerate(clean.pages, 1):
                ocr_row = observed[document['id'], page]
                if ocr_row['source_sha256'] != expected_pages[document['id'], page]['sha256']: raise ValueError('OCR page provenance mismatch')
                expected_metrics.append(dict(document_id=document['id'], page=page, **token_metrics(pdf_page.extract_text(), ocr_row['text'])))
        if receipt['metrics'] != expected_metrics: raise ValueError('retained OCR metrics changed')
        n = sum(m['expected_tokens'] for m in expected_metrics); m = sum(m['observed_tokens'] for m in expected_metrics); hit = sum(m['matched_tokens'] for m in expected_metrics)
        for key, expected in dict(pages=len(expected_metrics), expected_tokens=n, observed_tokens=m, matched_tokens=hit, token_recall=hit/n, token_precision=hit/m if m else 0.).items():
            if row[key] != expected: raise ValueError('aggregate scan metric mismatch')
        pages_read = {key for key, r in observed.items() if r['exit_code'] == 0}
        if receipt['answer'] is not None:
            if grade(tasks[entry['evaluator_task_id']], receipt['answer'], pages_read) != receipt['result']: raise ValueError('business grading changed')
        elif receipt['result']['strict_success'] or receipt['result']['score'] != 0 or not receipt['parser_error']:
            raise ValueError('failed extraction counted as business success')
        if row['strict_success'] != receipt['result']['strict_success'] or row['score'] != receipt['result']['score'] or row['parser_error'] != receipt['parser_error']: raise ValueError('business summary mismatch')
        total = totals[row['profile']]; total['presentations'] += 1; total['pages'] += len(expected_metrics)
        total['expected_tokens'] += n; total['observed_tokens'] += m; total['matched_tokens'] += hit
        total['strict_successes'] += row['strict_success']
    for profile, total in totals.items():
        expected = {k: total[k] for k in ('presentations', 'pages', 'strict_successes')}
        expected.update(token_recall=total['matched_tokens']/total['expected_tokens'], token_precision=total['matched_tokens']/total['observed_tokens'] if total['observed_tokens'] else 0.)
        if report['profiles'][profile] != expected: raise ValueError('profile summary mismatch')
    return dict(integrity_passed=True, presentations=len(entries), profiles=report['profiles'], scope='Retained OCR text/metric/business-result integrity; no new OCR, model inference or independent validation.')


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build'); b.add_argument('--output', required=True)
    q = sub.add_parser('qualify'); q.add_argument('--input', required=True); q.add_argument('--run-dir', required=True); q.add_argument('--report', required=True); q.add_argument('--workers', type=int, default=2)
    a = sub.add_parser('check'); a.add_argument('--input', required=True); a.add_argument('--report', required=True)
    args = parser.parse_args()
    if args.command == 'build': print(build(args.output))
    elif args.command == 'check': print(json.dumps(check(args.input, args.report)))
    else:
        if not 1 <= args.workers <= 4: raise ValueError('workers must be 1..4')
        print(json.dumps(qualify(args.input, args.run_dir, args.report, args.workers)['profiles']))

if __name__ == '__main__': main()
