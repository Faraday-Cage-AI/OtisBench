# Raw industrial measurements and condition assessment

This track contains **48 synthetic cases across 12 analysis families**, each with
four authored conditions: normal, fault, missing evidence and boundary/challenge.
They are raw CSV measurement tasks, not precomputed aggregate questions. Condition
names and seeds remain evaluator metadata. Counts do not imply independently
validated industrial deployments or 48 independent failure mechanisms.

## Native coverage

| Analysis family | Raw observations | Decision work |
|---|---|---|
| Vibration order | Uniform velocity waveform and timestamps | RMS, DFT peak, shaft order and qualified diagnosis |
| Bearing impulsiveness | Acceleration waveform | RMS, crest factor and non-excess kurtosis |
| Thermal soak | Temperature trace | Known duration, interrupted soak and absolute excursion |
| Pressure decay | Absolute pressure and sensor temperature | Temperature compensation, linear leakage trend and uncertainty |
| Motor phase current | Three current channels | Phase RMS, imbalance and missing-channel handling |
| Tool wear prediction | Timestamped wear measurements | Trend, future-observation interval and threshold-crossing estimate |
| SPC | Chronological part dimensions | Fixed-baseline z scores, special-cause point and same-side run |
| Energy meter | Cumulative energy, reset flags and good-unit counts | Reset-aware consumption, tariff-boundary splitting and specific energy |
| Cold-chain storage | Temperature logger trace | Exposure duration, observation gaps and lot disposition |
| Redundant sensors | Two channels plus independent reference | Individual and common-mode bias |
| Flow mass balance | Inlet/outlet flow and tank inventory | Integrated loss and bounded measurement-error uncertainty |
| Cohort failure risk | Complete and censored asset follow-ups | Complete-case risk, Wilson interval and uncertainty-aware action |

Four conditions are authored variations within a family, not four new families.
The benchmark does not infer true real-world root cause from synthetic waveforms.
Rules, thresholds, units, required metrics and operating assumptions are supplied
in the public policy. The agent derives its own assessment from raw evidence.

## Evidence and execution contract

1. Read the asset and analysis policy.
2. List measurement streams and read the complete frozen source through pages of
   at most 64 rows. Every page includes the CSV header, total rows, returned rows
   and next cursor. Overlapping reads do not inflate coverage.
3. Submit a complete typed assessment, including the operational decision.
4. Obtain single-use approval bound to the exact assessment and source commitment.
5. Execute it into the asset/quality/maintenance records.
6. Read back that persisted result, then finish with its assessment ID.

Decisions have explicit simulated effects:

| Decision | Asset / quality state |
|---|---|
| Continue | Operating, released |
| Inspect | Held for investigation; inspection work order |
| Stop | Stopped, held; investigation work order |
| Service | Maintenance required, held; service work order |
| Quarantine | Held, quarantined; quality work order |

An inspection is a hold pending investigation, not permission to release.
Approval grants permission; it does not certify analytical correctness. A wrong
but typed assessment can execute exactly as submitted, then fail the final
grader. The engine never inserts reference metrics or chooses an action for the
agent. Unauthorized execution, mismatched approvals and approval reuse are
critical violations and set the score to zero.

This is an offline assessment and controlled-record simulator. It does not drive
live machinery, perform physical maintenance or model every post-intervention
failure. It complements the longer manufacturing and procure-to-pay tracks.

## Missing data and uncertainty

The policy specifies valid sample counts/coverage and whether interpolation is
permitted. Bad/missing samples are not automatically zeroed or interpolated.
Intervals with missing endpoints or excessive gaps break thermal/exposure/flow
coverage. A vibration spectrum requires the complete uniform record. Cohort
censoring does not silently become survival. Energy meter resets are recoverable
only under an explicit reset-at-the-previous-sample contract.

Pressure decay uses OLS slope uncertainty. Tool wear uses a future-observation
prediction interval, which includes observation noise as well as fitted-mean
uncertainty. The supplied multiplier is a declared approximation, not guaranteed
95% coverage. A linear threshold-crossing estimate is not a calibrated remaining
useful life distribution. Flow uncertainty follows the stated absolute sensor
error bound; the toy model assumes tank measurements have no error.

The cohort task is complete-case risk over a common follow-up horizon, not a
lifetime survival model; it assumes representative independent complete cases.
SPC uses a disclosed two-rule action plan rather than all WECO or Nelson rules.
Thresholds are authored benchmark policies, not claims of regulatory or equipment
certification. These limitations remain part of the release evidence.

## Running and exporting

```bash
otisbench list --track sensors
otisbench export-agent --task sensor-vibration_order-fault --output runs/sensor-startup.json
otisbench export-sensor-data --task sensor-tool_wear_prediction-boundary \
  --output-dir runs/wear-data
otisbench sensors --task sensor-vibration_order-fault \
  --agent-command 'python examples/vibration_agent.py' \
  --output runs/vibration.json
otisbench replay runs/vibration.json
```

The data export contains raw observations, public policy, asset state and content
hashes. It omits case seeds, condition labels, reference metrics, solutions and
future outcomes. The example agent supports the four vibration-order cases only;
it is not a solver or model result for the other eleven families.

The persistent JSONL protocol is `faraday-manufacturing/1` with track `sensors`.
Return one `{tool, arguments}` JSON object per decision. Each episode allows 80
calls and 120 simulated minutes. Startup contains a neutral goal, tool contracts
and budgets. Asset/stream/action IDs are opaque and round-trip through public
records and CSV content. Private grades are saved separately from the agent trace.
Keep evaluator files outside agent-accessible containers: a subprocess is a
transport, not a filesystem sandbox.

## Scoring and verification

Strict success requires every requested metric and decision to be correct,
complete evidence coverage, executed state, independent read-back, explicit finish
and no critical violation. Correct metric fields contribute 70 points; a fully
correct assessment earns 10 for execution, 10 for read-back and 10 for finish.
Wrong assessments receive no procedural completion points. Read-only activity
scores zero. Report family-macro strict success and per-family/domain results
separately from other benchmark tracks.

```
python scripts/qualify_sensors.py
python -m pytest tests/test_sensors.py
```

Full-catalog qualification is **reference consistency**, not independent sensor
truth or model performance. It checks replay, weak/unsafe controls and changes
every assessment field individually. A separate vibration control parses public
CSV pages without evaluator imports. Analytical fixtures and metamorphic tests
check known waveforms/moments, regression, uncertainty width, unit/time integration,
censoring, reset semantics, run-breaking and the exact-three-sigma boundary.

## Technical references and scope

The calculations follow standard mathematical techniques, with task-specific
simplifications and operating policies disclosed above:

- [NIST: least squares](https://itl.nist.gov/div898/handbook/pmd/section4/pmd431.htm).
- [NIST: prediction and the difference between prediction and fitted-mean uncertainty](https://www.itl.nist.gov/div898/handbook/pmd/section1/pmd132.htm).
- [NIST: control charts and additional run rules](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc32.htm).
- [SciPy: periodogram conventions](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html).

Real sensor datasets, independently reviewed signal/physics assumptions, more
complex transients, adaptive monitoring, held-out faults, probabilistic calibration
and matched-budget model runs remain broader validation work. Native synthetic
breadth does not establish superiority over specialized asset benchmarks.
