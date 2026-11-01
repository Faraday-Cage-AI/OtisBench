# Manufacturing extensions

These source-run tiers complement the nine packaged tracks. Each has its own catalog, scoring, and commands; use the linked technical guide for its interface and dependencies.

| Tier | Scope | Entry points |
|---|---|---|
| Temporal recovery | 64 variants; staggered engineering, quality, equipment, fixture and labor constraints | [Guide](../challenges/README.md), `challenges/temporal_workflows.py` |
| Material networks | 48 cases; 8 material-flow families; mass, cash, stock and resource ledgers | [Guide](manufacturing-networks.md), `scripts/manufacturing_networks.py` |
| Replenishment | 128 cases; 16 planning contracts; whole-lot awards and component fulfillment | [Guide](replenishment.md), `scripts/export_replenishment.py` |
| Hydraulic monitoring | UCI condition-monitoring measurements with grouped partitions | [Guide](hydraulic-real-data.md), `scripts/hydraulic_benchmark.py` |
| Visual inspection | VisA photographs and masks; source test split; image/pixel metrics | [Guide](visual-inspection.md), `scripts/visual_inspection_benchmark.py` |
| Supplier scans | Scanned commercial evidence, OCR, receiving and financial reconciliation | [Guide](supplier-scans.md), `scripts/supplier_scans.py` |
| ERP compatibility | Pinned upstream task catalog with Odoo business tools | [Guide](erp-compatibility.md), `mfg-erp` |

Dataset downloads, external ERP services, and evaluation campaigns are explicit operations. Installing OtisBench or listing a catalog does not start them.
