# Workflow development lineage and holdout boundaries

The current native shop-floor generator publishes 1,024 cases: 32 named routes ×
16 authored disruption contracts × 2 numeric draws. Counting the released
production routes at different abstraction levels gives:

| Inventory level | Groups | What is actually counted |
|---|---:|---|
| Named industrial routes | 32 | Ordered process-name sequences |
| Released production-route topology | 2 | A three-operation chain or a four-operation chain |
| Released route control sequences | 25 | Ordered control archetype plus exact authored rule text |
| Control sequence × declared disruption contract | 400 | Route-control grouping paired with a disclosed fault-contract label |

These counts are not equivalent units of skill. The two route topologies are
**not** two complete world/workflow state machines: scheduling, lots, tools,
qualifications, evidence changes, rework, recalls, inspection, orders, approval and
shipping behavior are outside this route-only graph. Likewise, the 400 grouped
labels do not prove 400 independently novel causal fault mechanisms. A control
formula does not validate the physics of every industrial process bearing its name.

The `workflow-lineage.json` preserves each
case's hashes and grouping, exact source hashes, route-control aliases and a
suggested public development partition. This makes the existing breadth auditable
without confusing process labels, control equations and dependency topology.

## Conservative overlap rejection

```sh
python scripts/audit_workflow_lineage.py inventory
python scripts/audit_workflow_lineage.py inventory --check
python scripts/audit_workflow_lineage.py overlap \
  --candidate candidate-workflow.json --output runs/candidate-lineage.json
```

The overlap command accepts an existing-generator case configuration, including
an arbitrary seed or task name. It reconstructs actual released route records,
traverses their predecessor chain, and compares control-kind/rule sequences.
Every current native case and a renamed/reseeded instance of that generator is
rejected as a final holdout. A new material label, industrial title, identifier,
quantity, timing, rate, budget or seed cannot turn that known generator lineage
into a distinct released-route/control structure. Numeric variants can still
test different binding constraints and feasibility; this inventory does not
dismiss their value as parameter cases.

Canonical chain signatures ignore IDs, row order, material/product names and
numeric parameters. They retain operation order, predecessor structure, control
archetypes and exact authored rule text. Unknown generators, disconnected/cyclic
records, missing instructions and non-chain graphs fail closed as unassessed.
Failure to analyze an unfamiliar graph is **not** a novelty certificate. Rule
hashes are not semantic proofs: rewording an equation could change a hash without
changing the underlying reasoning. No automated positive-admission command exists.

## Public development partitions

The inventory suggests a deterministic 60/20/remaining percent split by complete
control-sequence groups. All route-name aliases, all 16 disruptions and both draws
for one control sequence stay together. This avoids a particular form of cross-
partition leakage where different route names reuse the same ordered formulas.

These partitions are public and reuse known control primitives and fault
contracts. They are suitable for declared development/composition experiments;
they are not a secret final set, previously unseen mechanisms, a private generalization
result, or evidence of optimizer access separation. There are only two released
route topologies, so three mutually topology-disjoint partitions cannot be formed
from this generator. More seeds or relabeling cannot fix that constraint.
