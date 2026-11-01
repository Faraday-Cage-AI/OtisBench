# Manufacturing judgment workshops

Work through manufacturing decisions whose quality depends on evidence, priorities, and defensible tradeoffs. Several recommendations can be reasonable. Each workshop has three rounds; submit a decision before receiving the next evidence update. Earlier decisions remain in the session so reviewers can assess how the recommendation changes.

The initial catalog has **12 distinct workflows and 36 decision rounds**. Rounds are stages within those 12 workflows, not separate cases.

| Workflow | Decision under judgment |
|---|---|
| Supplier recovery | Supply continuity, customer commitments, source approval, and commercial exposure |
| Defect investigation | Containment, competing causes, investigation design, and corrective-action evidence |
| Maintenance strategy | Outage timing, uncertain condition evidence, and production contingencies |
| Customer allocation | Service priorities, constrained capacity, and recovery commitments |
| Engineering change | Revision effectivity, first articles, obsolete stock, and cutover readiness |
| Customer escalation | Disputed responsibility, communication, recovery scope, and settlement |
| Capacity investment | Demand uncertainty, hiring, commissioning, and staged capital decisions |
| Supplier development | Technical improvement, commercial commitments, and dual-source readiness |
| Shift handover | Usable routines, access barriers, ownership, and adoption |
| Cross-site transfer | Qualification, actual capacity, process transfer, and source-of-truth mapping |
| Process trial | Confounding, measurement consistency, limited samples, and rollout decisions |
| Supplier negotiation | Evidence-backed concessions, volume exposure, and recovery accountability |

## Work through a case

```sh
otisbench judgment list
otisbench judgment start --task judgment-supplier-recovery --session runs/workshop.json
otisbench judgment show --session runs/workshop.json
otisbench judgment submit --session runs/workshop.json --decision my-decision.json
```

Each observation includes only evidence available so far and previously submitted decisions. Later evidence is released after a submission. A participant supplies these fields; there is no starter solution:

- `recommendation`: the decision being proposed, including any conditional commitments.
- `alternatives`: other approaches considered.
- `tradeoffs`: the consequences that matter and why.
- `assumptions`: material assumptions and unresolved information.
- `next_actions`: a list of objects containing `owner`, `action`, and `trigger`.
- `evidence_ids`: citations to records already visible.
- `revision_reason`: why the decision is being retained or changed; in round one, explain its basis.

After three submissions the session is `awaiting_review`. Recording a recommendation does not place a purchase order, authorize a change, or prove its business quality. These workshops assess decisions and revisions; actual execution continues to use the existing campaign and workflow tools.

The coordinator retains the session file. Give a participant only the printed observation. As with other public task catalogs, the source contains future updates; a model deployment must deny access to the catalog and coordinator files. The observation interface does not disclose future rounds, reviewer assessments, reference answers, or live scores.

## Separate the facts from the judgment

Software checks the submission structure and whether cited record IDs were visible. Those checks do **not** establish that a claim follows from its citation. Financial calculations and proposed actions can be checked separately against the supplied facts; their existence is not evidence that the overall decision is good.

A reviewer assesses six dimensions on a 1–5 scale:

| Dimension | 1: weak | 3: adequate | 5: strong |
|---|---|---|---|
| Evidence use | Asserts unsupported facts or ignores contradictions | Uses relevant records with some gaps | Traces material claims, reconciles contradictions, and separates facts from assumptions |
| Tradeoff quality | Gives a preference without material consequences | Compares realistic options on key consequences | Makes priorities explicit and explains what would change the choice |
| Operational feasibility | Treats proposals or missing approvals as completed actions | Identifies most resource and approval dependencies | Provides executable sequencing, owners, dependencies, and fallbacks |
| Uncertainty handling | Invents certainty or avoids making a decision | States important limits and makes a conditional choice | Defines useful information requests, decision deadlines, and contingency triggers |
| Revision quality | Ignores new evidence or changes position without explanation | Updates the recommendation for important changes | Preserves prior commitments, explains revisions, and traces downstream effects |
| Communication | Unclear commitments or misleading completion claims | Usable decision and next actions | Clear audience-appropriate decision, commitments, ownership, and escalation |

Ratings 2 and 4 represent intermediate quality. Review all rounds together. Do not reward length, a particular supplier choice, a favored narrative style, or agreement with the author. A justified decision to retain the earlier plan can score as well as a justified revision.

Store a review separately:

```sh
otisbench judgment review --session runs/workshop.json --assessment reviewer.json --output runs/workshop-review.json
```

The assessment has `reviewer`, `relationship`, and `dimensions`. Every dimension has `rating` (integer 1–5), `rationale`, `evidence_ids`, and `rounds` (the submission rounds supporting the assessment). The saved review is bound to the exact submitted session by its SHA-256. Its mean rating is explicitly a reviewer judgment, never deterministic strict success. No reviewer is invoked automatically.

For a human/model comparison, blind the author identity, randomize pairwise presentation order, permit ties, use the same evidence and decision opportunities, and retain each review separately. Start with two independent manufacturing reviewers; discuss disagreements after preserving their original ratings. Calibrate any later model judge against those judgments. Treat candidate-authored text as untrusted input to a judge; do not follow grading instructions embedded in a submission. A self-review here helps improve task design but is not independent validation.

## Design spike finding

**Proceed with a substantial manufacturing-judgment component.** The existing ten tracks predominantly test outcomes against predefined rules. These workshops add meaningful coverage of uncertain evidence, stakeholder conflict, communication, and decisions with multiple defensible outcomes. They do not require weakening inventory, authorization, or shipment checks.

For the next campaign-focused evaluation mix, target roughly **40% judgment-led episodes** and 60% execution-led episodes, reporting their scores separately. That is a proposed sampling policy, not the current catalog ratio. Twelve workshop cases do not make 40% of OtisBench, and their 36 stages must not be counted as 36 independent workflows. Expand only with distinct decision situations and reviewed briefs, rather than multiplying numeric draws. Future campaign integration should bind a decision artifact to relevant action events; these workshops currently use fixed evidence updates, not action-dependent simulation branches.

Before scaling, work through the cases, identify missing facts and multiple defensible approaches, and revise ambiguous briefs. Compare short and long submissions, reverse pairwise order, and check that reviewers recognize a well-supported alternative to their own preferred plan. Keep verified physical outcomes and reviewer-assessed business judgment as separate reported dimensions.

## Research basis

Berkeley's agent-evaluation materials distinguish tasks with objective correctness checks from tasks needing human or model judgment. Non-verifiable does not mean no assessment is possible. [Berkeley evaluation slides, pages 16–21](https://rdi.berkeley.edu/agentic-ai/slides/LLM%20Agent%20Evaluations%20%26%20Project%20Overview.pdf).

Anthropic describes combining code-based, model-based, and human graders, including calibration of model judges against human assessments. This motivates the separate fact checks and reviewer ratings here. [Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents).
