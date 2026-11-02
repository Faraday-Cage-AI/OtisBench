# Introducing OtisBench: from customer order to customer shipment

Faraday Research · November 1, 2026 · Benchmark version 1.4.2

[Read on the Faraday website](https://faradaycompute.com/research/otisbench) · [Benchmark card](../BENCHMARK_CARD.md)

## What we set out to measure

A customer order is a promise that crosses departments. Engineering defines what must be built. Purchasing secures the right material. Production needs qualified people, available machines, and workable process settings. Quality decides what can be released. Shipping must deliver the correct serialized units before the customer window closes.

OtisBench evaluates whether an AI can carry that promise through a modeled manufacturing operation. It combines engineering problems, operational tools, changing evidence, and persistent plant state. A plausible plan is only the beginning: execution tracks check the records and physical or financial outcomes represented by the environment.

We built OtisBench 1.4.2 with ten outcome-scored tracks, 32 manufacturing routes, 1,024 individual manufacturing workflows, 128 production campaigns, and twelve staged judgment workshops. Its breadth comes from connecting different kinds of work, while retaining separate measures for what each task actually tests.

## Eight systems. One operational consequence.

The environment models the records and actions that connect an industrial order. These are authored software environments; the system names describe operational roles, not a claim that every episode connects to a live commercial installation.

An engineering revision can invalidate process settings and approvals. A quality hold can make reserved inventory unusable. A machine change still requires qualified personnel and an available fixture. A shipment depends on released serials, and in a campaign it creates receivables that fund later work. Correctness must survive those dependencies.

| System | What the agent must coordinate |
| --- | --- |
| ERP | Customer orders, quantities, dates, budgets, and commercial commitments |
| MES | Routes, machines, resource bookings, operations, and work in progress |
| SCM | Supplier purchases, lead times, dispatch capacity, and certificates |
| WMS | Material lots, reservations, finished stock, serials, and shipments |
| PLM | Drawing revisions, process instructions, and engineering changes |
| QMS | Inspection, nonconformance, rework, containment, and release |
| CMMS | Condition alerts, repairs, calibration, tooling, and maintenance stock |
| HR | Operator availability, qualifications, and work assignments |

## A broad catalog with distinct tests of competence

OtisBench spans discrete production, process manufacturing, engineering calculations, commercial reconciliation, documents, geometry, and factory economics. Machining and fabrication sit alongside casting, molding, electronics, batteries, surface treatment, mechanical assembly, chemicals, food, textiles, glass, and ceramics.

Catalog size and conceptual diversity are different measures. The 1,024 workflow cases are 32 routes × 16 disruption contracts × two parameter draws. The 128 campaigns are those 32 routes under four operating profiles. Parameter variation increases test coverage; it does not turn every case into a distinct operational concept. Track results keep their own units and should not be collapsed into a synthetic universal score.

| Track | Catalog | What is checked |
| --- | --- | --- |
| Production campaigns | 128; 12–96 orders each | Order completion, shared resources, treasury and spare-stock reconciliation |
| Manufacturing workflows | 1,024; 32 routes | Conforming production, traceability, release, shipment, time and budget |
| Engineering | 84; 42 families | Exact outputs and numerical tolerances |
| Supply chain | 96; 24 families | Reconciliation, approval, posting and read-back |
| Procure to pay | 48; 12 contracts | Linked purchasing, receipt, quality, invoice and payment state |
| Sensor analysis | 48; 12 families | Diagnosis, evidence, recommended action and uncertainty |
| Procurement documents | 32 packets; 8 contracts | Decisions with document and page evidence |
| CAD and drawings | 72; 12 part families | Executable solids, geometry, datums and volume |
| Enterprise execution | 58; 18 families | Completed criteria, authorization, economics and timeliness |
| Factory seasons | 12; 26 weeks each | Profit, demand margin, fill rate, cash and cost decomposition |

Additional source-run tiers add 64 temporal recovery variants, 48 material-network cases, and 128 replenishment cases. They cover changing evidence schedules, nested and shared subassemblies, reconvergent material flows, recycling, inter-site transfers, supplier capacity, minimum order quantities, pack sizes, and allocation from components to shipments. These remain separate catalogs with their own entry points.

## A short example: recovering a disrupted order

Consider a pump-assembly order. The agent reads the customer commitment, released engineering instructions, material lots, and resource records. It derives the process controls required by the route, reserves eligible material, and schedules the equipment, operator, and fixture. Production consumes that reserved input and carries the resulting work in progress through later operations.

The catalog introduces sixteen disruption contracts. A late material hold requires a disposition or replacement supply. A drawing change requires current instructions and recalculated settings. A breakdown requires qualified alternate capacity or recovery of interrupted work. A failed inspection requires disposition, exact authorization for rework, and new measurements before release.

This walkthrough illustrates the task design, not an observed model trajectory. Compound-recovery cases combine engineering effectivity, held material, machine failure, and nonconformance. Other contracts exercise expiring certifications, tool life, calibration, outside processing, customer allocation, serial recalls, batch capacity, overtime, shared fixtures, split lots, and late inbound material.

An individual workflow permits up to 240 tool calls and 2,400 manufacturing minutes. Reads and attempted actions consume time. An agent must obtain current evidence and execute within the remaining window; waiting for perfect information can itself make delivery infeasible.

## From one completed job to a plant that keeps running

Production campaigns keep one plant state across 12, 24, 48, or 96 customer orders. Their horizons and global decision budgets range from 2,880 to 23,040 manufacturing minutes and tool calls. Each order also retains its own 240-call limit. These are simulated operating horizons and decision limits, not measured wall-clock model runtimes.

Orders share machines, employees, fixtures, tooling, supplier dispatch capacity, cash, and maintenance stock. A locally convenient purchase can consume the cash needed for the next order. A machine trip can interrupt work already in progress elsewhere. A replacement tool or repair consumes finite kits that must themselves be replenished.

Supplier reservations lock 20% deposits. Unused bookings can incur cancellation charges or lose deposits when they expire. Actual customer shipments produce receivables collected 240 manufacturing minutes later. Preventive service trades present downtime, cash, and a repair kit for temporary condition-trip coverage. These rules make commitments persist beyond the action that created them.

Strict campaign completion requires every order to pass, supplier commitments to be resolved, an explicit campaign finish, and reconciled financial and spare-stock ledgers within the horizon. Completing an early order is useful progress; it does not establish that the agent can sustain the whole campaign.

## What the software can verify

For the primary manufacturing workflows, shipped customer units contribute 40 points, conforming quality release 20, route completion 10, serial genealogy 10, on-time and within-budget fulfillment 10, and current revision, required containment, and final evidence 10. Strict success requires every check. Critical authorization or product-release violations set the score to zero.

Approvals bind to exact action payloads and the current engineering revision. Reserved material cannot be silently consumed twice. Unreleased or invalid serials cannot become valid shipments merely because the agent says the order is complete. These checks tie credit to the environment state.

Other tracks use different contracts: geometry checks for CAD, source-page evidence for procurement documents, exact schemas and tolerances for engineering, and economic outcomes for factory seasons. An automatically checked answer is correct relative to the implemented contract; that does not prove the contract captures every consideration a practitioner would apply.

## The work without one provably correct answer

Some consequential manufacturing decisions admit several defensible answers. Should a team expedite a fragile supplier or qualify another source? Which customer receives constrained capacity? Does uncertain condition evidence justify a maintenance outage? When should a process trial become a production change?

OtisBench includes twelve judgment workflows: supplier recovery, defect investigation, maintenance strategy, customer allocation, engineering change, customer escalation, capacity investment, supplier development, shift handover, cross-site transfer, process trial, and supplier negotiation. Each contains three decision rounds, giving twelve cases and 36 stages, rather than 36 independent cases.

The participant commits a recommendation before the next evidence update appears. Submissions record alternatives, tradeoffs, assumptions, evidence citations, next actions with owners and triggers, and reasons for revising or retaining the decision. Reviewers can inspect whether new evidence changes the recommendation and whether downstream commitments remain coherent.

Software verifies the submission structure and whether cited record IDs were visible. It does not establish that a citation supports the claim, that the recommendation is feasible, or that its tradeoffs are sound. Reviewers assess evidence use, tradeoff quality, operational feasibility, uncertainty handling, revision quality, and communication on separate 1–5 scales.

These ratings remain separate from deterministic strict success. A submitted recommendation does not execute a purchase, obtain approval, or demonstrate business value. The workshops currently release fixed evidence updates; they do not simulate action-dependent consequences of the recommendation. Independent, blinded review and preserved disagreements are needed to support stronger claims about decision quality.

## Current model results

The current maintainer-reported results are reproduced below. Opus 5 leads the reported table at 38% task pass rate, 44% weighted requirements, and 25% cross-system completion. GPT-5.6 Sol follows at 36%, 42%, and 24%. Across the listed models, task pass rates range from 21% to 38%.

The table shows substantial remaining headroom under the reported evaluation. It does not identify the cause of any individual failure. Task-level traces are needed to separate calculation errors, stale evidence, invalid authorization, planning failures, and incomplete execution.

This summary does not include its task denominator, track mix, metric aggregation formulas, exact model snapshots, agent configuration, repeat count, uncertainty intervals, or linked run artifacts. Those details are needed to reproduce the figures and assess small differences. The weighted-requirements column should not be equated with the primary workflow outcome score without its aggregation specification. Judgment-workshop ratings are not presented in this table.

| Model | Task pass rate | Weighted requirements | Cross-system completion |
| --- | --- | --- | --- |
| Opus 5 | 38% | 44% | 25% |
| GPT-5.6 Sol | 36% | 42% | 24% |
| GPT-5.5 | 33% | 39% | 22% |
| Opus 4.8 | 32% | 38% | 21% |
| Grok 4.5 | 31% | 37% | 20% |
| Opus 4.7 | 28% | 34% | 18% |
| GPT-5.4 | 26% | 32% | 17% |
| Gemini 3.1 Pro | 25% | 31% | 16% |
| GLM-5.2 | 23% | 29% | 14% |
| Sonnet 4.6 | 21% | 27% | 13% |

## An operational record that can be inspected

Run artifacts retain submitted actions, tool results, applied events, state hashes, and terminal checks. Replay reconstructs the transitions and checks the final results. Campaign journals support recovery from interruptions; source fingerprints identify the environment used.

The participant receives public tasks, tool contracts, observations, and its own history. Reference calculations, future event schedules, live scores, and evaluator traces belong outside its context. Public source availability makes process isolation important: a tool interface alone does not prevent an agent with host access from reading evaluator files.

A complete model report should bind the benchmark commit and manifest to the task selection, model snapshot, prompts, reasoning settings, budgets, retries, costs, and replayable artifacts. Replay tests consistency with the implemented environment. It does not independently validate the realism of the environment or establish industrial safety.

## What the benchmark establishes—and what remains open

OtisBench offers broad, executable coverage of connected manufacturing work. Its strongest design feature is that material, capacity, engineering revisions, approvals, quality, and cash can constrain the same episode. The judgment workshops extend that scope to decisions whose quality cannot be reduced to a single exact output.

The core commercial records, workflows, parts, and documents are authored task content. Optional measurement and visual-inspection extensions use attributed external datasets; that does not make the core suite observed customer operations. Passing a modeled process is evidence about that process contract, not proof of performance on a live plant, a certified control system, or every commercial ERP.

Public tasks can become familiar through repeated use. More parameter draws do not substitute for structurally different held-out workflows. Reviewer preference, domain expertise, and calibration affect judgment scores. Independent practitioner review, held-out task designs, repeated model runs, and failure analysis would strengthen the evidence.

The scope is intentionally described in concrete terms rather than as a claim of universal comprehensiveness. Physical handling, every vendor integration, unconstrained human negotiation, and long-term organizational adoption are not established by the catalog. The research question remains practical: which parts of an industrial commitment can an agent execute reliably, and where does it still need human judgment or intervention?

## Inspect the contracts. Run your own agent.

The public repository includes the task catalogs, evaluator code, benchmark card, integration documentation, and replay tools. Start with a bounded workflow, inspect its action trace and terminal checks, then test sustained campaigns. Report execution outcomes and reviewer assessments separately.

```bash
git clone https://github.com/Faraday-Cage-AI/OtisBench.git
cd OtisBench
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
otisbench list --track workflow
otisbench export-agent --task mfg-flow-pump_assembly-16-01 --output agent-input.json
# Supply your own agent implementation.
otisbench workflow --task mfg-flow-pump_assembly-16-01 \
  --agent-command 'python /absolute/path/to/my_agent.py' --output runs/pump.json
otisbench replay runs/pump.json
```

## Source contracts

[Benchmark card](../BENCHMARK_CARD.md) · [Manufacturing workflows](manufacturing-workflows.md) · [Production campaigns](production-campaigns.md) · [Judgment workshops](manufacturing-judgment.md) · [Scoring and protocol](methodology.md) · [Agent isolation](agent-isolation.md)
