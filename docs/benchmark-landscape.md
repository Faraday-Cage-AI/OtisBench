# OtisBench in the benchmark landscape

OtisBench asks whether an agent can carry manufacturing work through engineering, production, recovery, quality release, and delivery while managing shared resources and cash. Its identity is the depth and breadth of that operating workload.

| Benchmark | Core workload | Evaluation emphasis |
|---|---|---|
| [LarkBench](https://larkagents.com/blog/larkbench/article.html) | Recurring distributor purchasing across a vendor product line | Profit after costs over a 26-week season, compared with purchasing rules |
| [ICCA Bench](https://oroagents.com/benchmarks/icca-bench) | Purchasing at a produce-wholesale desk over a 90-day quarter | Delayed consequences, paired counterfactual worlds, adaptation, and transfer from earlier experience |
| OtisBench | Engineering-to-shipment manufacturing execution and sustained plant campaigns | Production completion, conformance, traceability, delivery, approvals, financial reconciliation, and separate reviewer-assessed judgment |

## The manufacturing challenge

**Transform the product.** Material becomes work in progress, moves through an ordered production route, and becomes inspected, released, serialized product. Resource choices and process settings influence whether those steps succeed.

**Coordinate the plant.** Campaign orders share a machine fleet, qualified workforce, fixtures, tooling, maintenance stock, supplier dispatch windows, and cash. The 12-, 24-, 48-, and 96-order profiles sustain those dependencies across a persistent episode.

**Recover while commitments remain.** Changing drawings, held lots, equipment trips, failed inspections, and delayed receipts create consequences for work already underway. The agent must execute recovery through business tools and retain evidence for the resulting state.

**Span technical and commercial work.** Ten outcome-scored tracks cover engineering, CAD, measurements, documents, supply-chain decisions, purchasing lifecycles, production, enterprise execution, and factory economics. Twelve additional judgment workflows introduce competing priorities and evolving evidence across three decision rounds each.

**Inspect what happened.** Execution traces, business records, financial and stock checks, and deterministic replay make operational outcomes inspectable. Judgment workshops retain decisions and revisions for separate reviewer assessment.

## Interpret the comparison

These benchmarks target different capabilities. A larger catalog is not a difficulty multiplier, and tool-call budgets, weekly decisions, and paired-world episodes are different units. OtisBench’s campaigns do not currently implement ICCA’s paired-world learning and transfer protocol. Its judgment workshops assess revised recommendations; they do not establish learning from a controlled counterfactual experiment.

Use the workload and measurement contract to choose an evaluation. Model-performance comparisons need the same models, settings, budgets, task selection, and appropriate per-track metrics. OtisBench’s positioning here describes its manufacturing scope, not a measured performance ranking against the other benchmarks.

Sources: the publishers’ [LarkBench article](https://larkagents.com/blog/larkbench/article.html) and [ICCA technical report](https://oroagents.com/benchmarks/icca-bench), accessed November 1, 2026. [Detailed LarkBench scope comparison](larkbench.md).
