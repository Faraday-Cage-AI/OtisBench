# Agent integration and isolation

OtisBench agents run as persistent JSONL processes. The evaluator writes a decision object to stdin; the agent returns one JSON action on stdout. Keep diagnostics on stderr. Wire protocol `faraday-manufacturing/1` remains stable across the OtisBench naming change.

The workflow startup payload contains a neutral fulfillment goal, opaque task handle, tool argument contracts, and episode limits. Subsequent decisions include the last projected result, current minute, and remaining calls. The agent investigates business records and submits every action and process value itself.

```json
{"tool":"read","arguments":{"system":"ERP"}}
```

## Deployment boundary

Keep the evaluator's source, catalogs, reference policies, tests, reports, and private artifacts outside the agent filesystem. Expose the public startup contract and tool responses through the transport. Ordinary `--agent-command` starts a subprocess with the host's permissions; use a separate container or restricted runtime for agents with filesystem or code tools.

## Provided macOS launcher

```bash
otisbench isolated --track workflow --task mfg-flow-precision_cnc-01-01 \
  --agent-file /absolute/path/to/standalone_agent.py --output runs/isolated.json
otisbench replay runs/isolated.json
```

The macOS launcher stages one standalone Python file and starts the base runtime with `-I -S`. The agent gets standard-library access and scratch storage. OS rules deny evaluator-file access, inherited credentials, network connections, subprocess creation, and host writes outside scratch. Workflow, supply-chain, procurement, sensors, CAD, and documents are supported.

Limits include 60 CPU seconds per process, 4 MiB per file, 64 open file descriptors, a decision timeout, and a response-size limit. The evaluator's CAD worker remains outside the agent boundary. The launcher requires macOS `sandbox-exec`; unsupported platforms return an error. For networked agents, place provider access behind a host-side proxy with a separate restricted agent runtime.

## Trace boundary

Workflow observations use business-field allowlists. IDs are consistently aliased per episode. Worked formulas, future event outcomes, reference answers, scenario labels, internal grading flags, unknown evaluator fields, and live scores are filtered from agent messages. Error codes identify failed actions without supplying the answer or a recovery plan.

Measurements, receipt certificates, equipment state, source revisions, and quality bulletins are observable business evidence. The evaluator stores its complete trace and grade separately from the agent's projected trace. Replay uses the evaluator artifact.
