# Contributing to OtisBench

A task change should specify its manufacturing decision, observable source evidence, action contract, physical or financial consequence, and terminal checks. Prefer new operational structures and failure modes to extra parameter draws.

Keep public task inputs separate from evaluator logic. Never put expected process values, reference actions, scenario hints, live scores, or grading annotations into the agent transport. Add boundary tests when introducing observable fields.

For execution changes, cover stock/cash conservation, resource occupancy, approvals, event timing, idempotency, and replay where relevant. Test an incorrect action as well as a feasible action. Keep track scores and catalog dimensions distinct.

Run focused tests before submitting changes:

```bash
python -m pytest tests/test_otisbench.py tests/test_agent_boundary.py tests/test_shopfloor.py tests/test_campaign.py -q
python scripts/build_manifest.py
python scripts/build_manifest.py --check
```

Regenerate CAD or document assets only when their generators change. Full qualification scripts and model campaigns are explicit operations with separate artifacts. Do not commit credentials, local `.env` files, dataset caches, or agent run directories.
