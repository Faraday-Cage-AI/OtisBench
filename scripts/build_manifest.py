"""Freeze authored supply tasks and fingerprint release inputs; --check is read-only."""
from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path
from faraday_manufacturing_benchmark import __version__
from faraday_manufacturing_benchmark.catalog import TASKS
from faraday_manufacturing_benchmark.campaign import catalog as campaign_catalog, PROFILES as CAMPAIGN_PROFILES
from faraday_manufacturing_benchmark.cli import workflow_catalog,workflows
from faraday_manufacturing_benchmark.season import CASES
from faraday_manufacturing_benchmark.supply_cases import catalog
from faraday_manufacturing_benchmark.procurement_cases import catalog as procurement_catalog,build as build_procurement,CONTRACTS
from faraday_manufacturing_benchmark.sensor_cases import catalog as sensor_catalog,build as build_sensor,SPECS,CONDITIONS
from faraday_manufacturing_benchmark.cad_cases import catalog as cad_catalog,build as build_cad,FAMILIES as CAD_FAMILIES,MODES as CAD_MODES
from faraday_manufacturing_benchmark.document_cases import catalog as document_catalog,build as build_document,FAMILIES as DOCUMENT_FAMILIES,MODES as DOCUMENT_MODES
from faraday_manufacturing_benchmark.shopfloor import digest
ROOT=Path(__file__).resolve().parents[1]


def encoded(value):return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    campaigns=campaign_catalog();campaign_data=encoded(campaigns);campaign_frozen=ROOT/'src/faraday_manufacturing_benchmark/data/campaign_tasks.json'
    if not args.check:campaign_frozen.write_bytes(campaign_data)
    elif not campaign_frozen.exists() or campaign_frozen.read_bytes()!=campaign_data:raise SystemExit('Frozen campaign catalog mismatch')
    tasks=catalog();frozen=ROOT/'src/faraday_manufacturing_benchmark/data/supply_chain_tasks.json';data=encoded(tasks)
    if not args.check:frozen.write_bytes(data)
    elif not frozen.exists() or frozen.read_bytes()!=data:raise SystemExit('Frozen supply cases differ from authored contracts')
    procurement=procurement_catalog();chain_frozen=ROOT/'src/faraday_manufacturing_benchmark/data/procurement_tasks.json';chain_data=encoded(procurement)
    if not args.check:chain_frozen.write_bytes(chain_data)
    elif not chain_frozen.exists() or chain_frozen.read_bytes()!=chain_data:raise SystemExit('Frozen procurement cases differ from authored contracts')
    sensors=sensor_catalog();sensor_frozen=ROOT/'src/faraday_manufacturing_benchmark/data/sensor_tasks.json';sensor_data=encoded(sensors)
    if not args.check:sensor_frozen.write_bytes(sensor_data)
    elif not sensor_frozen.exists() or sensor_frozen.read_bytes()!=sensor_data:raise SystemExit('Frozen sensor cases differ from authored contracts')
    cad=cad_catalog();cad_frozen=ROOT/'src/faraday_manufacturing_benchmark/data/cad_tasks.json';cad_data=encoded(cad)
    if not args.check:cad_frozen.write_bytes(cad_data)
    elif not cad_frozen.exists() or cad_frozen.read_bytes()!=cad_data:raise SystemExit('Frozen CAD cases differ from authored contracts')
    asset_root=ROOT/'src/faraday_manufacturing_benchmark/data/cad_assets';asset_manifest=asset_root/'manifest.json';assets=json.loads(asset_manifest.read_text())
    if set(assets['cases'])!={t['id'] for t in cad}:raise SystemExit('CAD public asset catalog mismatch')
    for filename,sha in assets['generator_sha256'].items():
        if hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()!=sha:raise SystemExit('CAD source pipeline changed; run scripts/build_cad_assets.py')
    for t in cad:
        entry=assets['cases'][t['id']]
        if entry['spec_sha256']!=digest(build_cad(t)):raise SystemExit('CAD frozen specification mismatch')
        for asset in entry['files'].values():
            if hashlib.sha256((asset_root/t['id']/asset['filename']).read_bytes()).hexdigest()!=asset['sha256']:raise SystemExit('CAD public asset hash mismatch')
    documents=document_catalog();document_frozen=ROOT/'src/faraday_manufacturing_benchmark/data/document_tasks.json';document_data=encoded(documents)
    if not args.check:document_frozen.write_bytes(document_data)
    elif not document_frozen.exists() or document_frozen.read_bytes()!=document_data:raise SystemExit('Frozen document catalog mismatch')
    document_root=ROOT/'src/faraday_manufacturing_benchmark/data/document_assets';document_manifest=document_root/'manifest.json';document_assets=json.loads(document_manifest.read_text())
    if set(document_assets['cases'])!={t['id'] for t in documents}:raise SystemExit('Document public asset catalog mismatch')
    for filename,sha in document_assets['generator_sha256'].items():
        if hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()!=sha:raise SystemExit('Document source pipeline changed; run scripts/build_document_assets.py')
    for t in documents:
        entry=document_assets['cases'][t['id']]
        if entry['spec_sha256']!=digest(build_document(t)):raise SystemExit('Document frozen specification mismatch')
        if {d['id'] for d in entry['documents']}!={d['id'] for d in build_document(t)['documents']}:raise SystemExit('Document file inventory mismatch')
        for doc in entry['documents']:
            for asset in [doc]+doc['pages']:
                if hashlib.sha256((document_root/t['id']/asset['filename']).read_bytes()).hexdigest()!=asset['sha256']:raise SystemExit('Document public asset hash mismatch')
    previous=json.loads((ROOT/'manifest.json').read_text());previous.update(version=__version__,
        campaign_cases=len(campaigns),campaign_route_families=len({t['family'] for t in campaigns}),
        campaign_profiles={k:dict(work_orders=v[0],horizon_minutes=v[1],max_tool_calls=v[0]*240,release_cadence_minutes=216 if v[0]>=48 else 180) for k,v in CAMPAIGN_PROFILES.items()},
        campaign_catalog_sha256=hashlib.sha256(campaign_data).hexdigest(),
        engineering_cases=len(TASKS),engineering_families=len({t['family'] for t in TASKS}),
        execution_cases=len(workflows()),execution_families=len({t['family'] for t in workflows()}),
        manufacturing_workflow_cases=len(workflow_catalog()),factory_cases=[asdict(c) for c in CASES],
        supply_chain_cases=len(tasks),supply_chain_families=len({t['family'] for t in tasks}),
        supply_chain_conditions_per_family=4,supply_chain_provenance='synthetic-authored',
        supply_chain_catalog_sha256=hashlib.sha256(data).hexdigest(),
        procurement_chain_cases=len(procurement),procurement_chain_lifecycles=1,
        procurement_chain_disruption_contracts=len(CONTRACTS),procurement_chain_parameter_draws=4,
        procurement_chain_catalog_sha256=hashlib.sha256(chain_data).hexdigest(),
        procurement_initial_source_sha256={t['id']:hashlib.sha256(encoded(build_procurement(t))).hexdigest() for t in procurement},
        sensor_cases=len(sensors),sensor_analysis_families=len(SPECS),sensor_conditions_per_family=len(CONDITIONS),
        sensor_catalog_sha256=hashlib.sha256(sensor_data).hexdigest(),
        sensor_raw_source_sha256={t['id']:hashlib.sha256(encoded(build_sensor(t))).hexdigest() for t in sensors},
        cad_cases=len(cad),cad_part_families=len(CAD_FAMILIES),cad_evidence_modes=len(CAD_MODES),cad_parameter_draws=2,
        cad_catalog_sha256=hashlib.sha256(cad_data).hexdigest(),cad_public_asset_manifest_sha256=hashlib.sha256(asset_manifest.read_bytes()).hexdigest(),
        procurement_document_cases=len(documents),procurement_document_contracts=len(DOCUMENT_FAMILIES),procurement_document_draws=2,procurement_document_modes=list(DOCUMENT_MODES),procurement_document_catalog_sha256=hashlib.sha256(document_data).hexdigest(),procurement_document_asset_manifest_sha256=hashlib.sha256(document_manifest.read_bytes()).hexdigest(),
        erp_compatibility_protocol='odoo-json2-business/1',erp_compatibility_source_revision='ceba3880af555129b5278e056a0c20f2fb5a0ba9',erp_compatibility_native_case_count_added=0,
        score_reporting='Separate track scores; do not pool incompatible units.',
        benchmark='OtisBench')
    previous.pop('superlative_claim_status', None)
    previous['advanced_tiers'] = {'temporal_workflow_variants': 64, 'material_network_cases': 48, 'replenishment_cases': 128}
    paths=[]
    for directory in ('src','scripts','tests','examples','docs','challenges','.github'):
        paths.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.md','.yml','.yaml'))
    paths.extend(ROOT/p for p in ('README.md','BENCHMARK_CARD.md','pyproject.toml','NOTICE','LICENSE','DATA_LICENSE','CONTRIBUTING.md','.gitignore','.gitattributes'))
    paths.extend(p for p in asset_root.rglob('*') if p.is_file() and p.suffix in ('.png','.step'))
    paths.extend(p for p in document_root.rglob('*') if p.is_file() and p.suffix in ('.pdf','.png'))
    previous['sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    blob=encoded(previous);path=ROOT/'manifest.json'
    if args.check:
        if path.read_bytes()!=blob:raise SystemExit('Release manifest is stale; run scripts/build_manifest.py')
        print('Manifest matches case catalogs and all fingerprinted release inputs.')
    else:path.write_bytes(blob);print(f'Frozen {len(tasks)} supply-chain decisions, {len(procurement)} procure-to-pay chains, {len(sensors)} sensor cases and {len(cad)} CAD cases; release manifest updated.')
    return 0

if __name__=='__main__':raise SystemExit(main())
