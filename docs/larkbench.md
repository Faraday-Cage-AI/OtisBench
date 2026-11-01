# Manufacturing scope: OtisBench and LarkBench

[LarkBench](https://larkagents.com/blog/larkbench/article.html) evaluates recurring purchasing for one distributor vendor across 15–30 products and 26 weeks. Its published design uses 160 books, three paired draws, demand-margin profit scoring, ordering baselines, and model comparisons.

OtisBench makes the manufacturing order the unit of work: engineering release, material eligibility, production, maintenance, quality, and shipment must reconcile.

| Dimension | LarkBench published design | OtisBench design |
|---|---|---|
| Core operational unit | Distributor/vendor purchasing book | Manufacturing order and production route |
| Decision horizon | One purchase decision per week, 26 weeks | 12–24-order shared-plant campaigns with up to 5,760 tool decisions; additional 26-week factory seasons |
| Material transformation | Purchasing and inventory economics | Material consumption, WIP, ordered operations, rework, finished product |
| Production resources | Distributor purchasing scope | Machines, labor qualifications, fixtures, tool life, calibration, batch limits |
| Disruption recovery | Demand, deliveries, and vendor information | 16 workflow disruption contracts, plus staggered temporal recovery |
| Engineering | Product purchasing decisions | 42 calculation/optimization families and route-specific controls |
| Quality evidence | Purchasing task inputs | Inspection, nonconformance, authorized rework, certificates, release |
| Geometry and measurements | Purchasing task inputs | CAD solids, drawings, raw time series, photographed inspection extensions |
| Completion | Purchasing economics | Actual shipment, genealogy, conformance, deadlines, budget, and authorization |
| Evaluation structure | Paired book draws, baselines, published model results | Ten track contracts, deterministic replay, family/contract metrics, paired factory comparisons |

OtisBench expands the manufacturing problem beyond replenishment into production and cross-system execution. Its persistent multi-order campaigns, temporal tier, and material networks add timing pressure, assembly joins, shared intermediates, recycling, and multi-site flow. Track scores describe their own operational outcomes; purchasing profit and manufacturing strict completion have different units.

Source: [LarkBench's complete article](https://larkagents.com/blog/larkbench/article.html), accessed November 1, 2026.
