# Real-Odoo compatibility adapter

`mfg-erp` provides a separate adapter over pinned ERP-Bench cases.
The nine native tracks keep their existing case counts. Downloaded upstream tasks
are not newly authored Faraday skills or additional native benchmark cases.

The adapter uses an actual Odoo 19/PostgreSQL runtime, not an in-memory substitute.
It supports pinned task download, baseline capture, fresh-container restoration,
constrained business RPCs, evaluator-side grading and exact replay checks. The
selected runtime is a locally retained immutable Docker image ID. Supply a compatible Odoo image when preparing the baseline.

## Lifecycle and boundary

`fetch` downloads the selected task at commit
`ceba3880af555129b5278e056a0c20f2fb5a0ba9` and checks every Git blob/hash.
`prepare` initializes a disposable fixture, captures a consistent PostgreSQL dump,
filestore and readable business-state digest, then removes the owned container.
Crons are disabled through an explicit Odoo configuration setting.

Each run restores SQL and filestore into a fresh container from that captured
image. Its readable baseline must match before any agent acts. The container has
no external network, no published ports or host bind mounts, three CPU quota,
4 GiB memory and a PID limit. A new fixture API key is generated evaluator-side;
credentials are never sent to the agent. Only containers with the adapter's own
random ownership label are removed at cleanup.

The agent receives the business instruction, public anchor date and a typed
allowlist. Its standalone Python file runs under the qualified offline macOS
boundary. It can query public records and create/write supported sales,
purchasing and manufacturing business records through Odoo's JSON-2 API. RPC
parameter, field, relation and method validation excludes identity/configuration,
server actions, arbitrary code, mail and attachment operations. Nested order-line
commands cannot introduce fields or models outside that business allowlist.
Commercially incorrect but schema-valid prices are permitted to persist and must
fail the business grader. The gateway has no reference prices or optimal plan.

The upstream credentials/access-script section is removed from startup because
this adapter supplies a different transport. No reference plan, original scenario
tables, grader code, model-facing correctness feedback or task-family label is
injected into the agent payload. The agent process closes before grader files are
copied into its private ERP fixture. The upstream terminal-state verifier is kept
unchanged. Gateway policy violations separately force adapter failure/zero while
retaining the upstream verdict for diagnosis.

## Replay scope

Replay restores the same SQL/filestore baseline, reexecutes recorded business
calls, and compares exact RPC responses, the declared readable business-record
projection and the full upstream verifier result. The projection is the explicit
field schema in `erp_protocol.py`; it is not a byte-identical hash of every
PostgreSQL/system table. Ordinary Odoo access context and active-record filters
apply to that projection. Keys are regenerated and audit timestamps are not exposed
by the read schema. Operational business dates remain checked where declared.

The runtime wall clock is not virtualized. Defaults or time-dependent actions can
make some episodes nonreplayable; the adapter rejects mismatches rather than
rounding or silently dropping them. Cross-date replay, every valid action sequence
and all 300 upstream tasks are not established by the selected qualification.
Local image, source-cache and baseline artifacts must be retained. Baselines are
evaluator-only artifacts; they must not be mounted into an agent environment.

## Commands

```bash
mfg-erp fetch --task 2000_easy_01_buy_only_baseline --cache runs/erp-compat/source
mfg-erp prepare --case-dir runs/erp-compat/source/2000_easy_01_buy_only_baseline \
  --output-dir runs/erp-compat/baselines/example --image <qualified-local-image>
mfg-erp run --snapshot runs/erp-compat/baselines/example \
  --agent-file examples/erp_buy_agent.py --output runs/erp-buyer.json
mfg-erp replay runs/erp-buyer.json --output-dir runs/erp-replay-evidence
python scripts/qualify_erp.py
```

Source preparation requires HTTPS access; execution containers and the agent are
offline. The host needs Docker and the existing compatible Odoo image. Qualification
uses the three explicitly selected cached baselines, not an implicit full-catalog
selection. Unsupported/missing dependencies fail; no simulated backend is silently
substituted.
