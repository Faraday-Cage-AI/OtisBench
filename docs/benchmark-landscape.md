# Benchmark scope comparison

OtisBench evaluates manufacturing execution across engineering, production, recovery, quality release, and delivery. Campaigns share resources and cash across customer orders.

| Benchmark | Core workload | Evaluation emphasis |
|---|---|---|
| [LarkBench](https://larkagents.com/blog/larkbench/article.html) | Recurring distributor purchasing across a vendor product line | Profit after costs over a 26-week season, compared with purchasing rules |
| [ICCA Bench](https://oroagents.com/benchmarks/icca-bench) | Purchasing at a produce-wholesale desk over a 90-day quarter | Delayed consequences, paired counterfactual worlds, adaptation, and transfer from earlier experience |
| OtisBench | Engineering-to-shipment manufacturing execution and sustained plant campaigns | Production completion, conformance, traceability, delivery, approvals, financial reconciliation, and separate reviewer-assessed judgment |

## OtisBench coverage

- Production consumes material, creates work in progress, and produces inspected, released, serialized units.
- Campaign orders share machines, staff, fixtures, tooling, maintenance stock, supplier capacity, and cash.
- Drawing changes, held lots, breakdowns, failed inspections, and late receipts require recovery actions.
- Ten tracks cover engineering, CAD, sensor data, documents, supply-chain decisions, purchasing, production, enterprise execution, and factory economics.
- Twelve judgment workflows retain recommendations and revisions for reviewer assessment.
- Execution artifacts retain actions, results, state hashes, and financial and stock checks for replay.

## Interpret the comparison

These benchmarks target different capabilities. A larger catalog is not a difficulty multiplier, and tool-call budgets, weekly decisions, and paired-world episodes are different units. OtisBench’s campaigns do not currently implement ICCA’s paired-world learning and transfer protocol. Its judgment workshops assess revised recommendations; they do not establish learning from a controlled counterfactual experiment.

Use the workload and measurement contract to choose an evaluation. Model-performance comparisons need the same models, settings, budgets, task selection, and appropriate per-track metrics. The comparison describes task coverage. It does not rank model performance across benchmarks.

Sources: the publishers’ [LarkBench article](https://larkagents.com/blog/larkbench/article.html) and [ICCA technical report](https://oroagents.com/benchmarks/icca-bench), accessed November 1, 2026. [Detailed LarkBench scope comparison](larkbench.md).
