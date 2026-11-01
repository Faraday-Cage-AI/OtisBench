# Temporal manufacturing recovery

**64 workflow variants: 32 manufacturing routes × 2 temporal draws.**

Engineering releases, quality dispositions, and machine trips arrive at different case-specific times. Agents must investigate current business records and adapt the production plan while the clock advances.

The manufacturing order requires procurement, irreversible production, equipment recovery, process calculations, inspection, authorized rework, release, and serialized shipment. Shared-fixture bookings constrain operation starts. Operator qualifications can expire before an operation ends. Premium equipment, replacement material, and rework compete for the production budget.

Business records expose review dates and condition alerts. The private event calendar stays evaluator-side. The customer deadline leaves insufficient route time after a blanket wait to minute 300, so timing and early decisions matter. Waiting a fixed 20 minutes does not settle all changes.

## Use the tier

From an installed source checkout:

```bash
python challenges/temporal_workflows.py list
python challenges/temporal_workflows.py run \
  --task temporal-precision_cnc-01 \
  --agent-file /absolute/path/to/standalone_agent.py \
  --output runs/temporal-example.json
python challenges/temporal_workflows.py replay runs/temporal-example.json
```

The launcher uses the macOS offline agent boundary, staging only the selected standalone Python file. It sends the same projected manufacturing JSONL tools as the primary workflow track. Agents receive the goal and business observations, derive values, and choose their own actions.

Artifacts retain agent and evaluator traces, launch metadata, source fingerprints, and terminal checks. Replay verifies source identity, every transition, and the terminal result. The temporal catalog extends the compound-recovery routes and is reported separately from the primary 1,024-case suite.

## Focused checks

```bash
python -m pytest challenges/test_temporal_workflows.py -q
```

Checks cover deterministic event schedules, exact clock jumps, fixture and qualification constraints, deadline feasibility bounds, source invalidation, replay corruption, agent-input filtering, and a bounded positive/negative policy pair.
