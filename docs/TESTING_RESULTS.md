# Testing results and evidence index

All values below come from the included raw recordings. The original report
uses eight single runs from 27 October 2026 at six switches, 4 Mbps application
load and 10 Mbps link capacity. The guarded loss run appears in both the scenario
results and method comparison, but counts once.

## Original report and presentation results

| Scenario | Method | Run ID | Receiver Mbps | UDP loss % | Verified recovery s |
| --- | --- | --- | ---: | ---: | ---: |
| Packet loss | RF + loss guard | [`20261027T150945Z-5b433df7`](../evidence/runs/report/20261027T150945Z-5b433df7/summary.json) | 3.972 | 0.644 | 3.300 |
| Packet loss | RF only | [`20261027T151025Z-7bbacb9c`](../evidence/runs/report/20261027T151025Z-7bbacb9c/summary.json) | 3.629 | 9.242 | Not observed |
| Packet loss | Fixed rules | [`20261027T151105Z-3f4808d8`](../evidence/runs/report/20261027T151105Z-3f4808d8/summary.json) | 3.970 | 0.716 | 3.351 |
| Normal | RF + loss guard | [`20261027T151646Z-776f29cf`](../evidence/runs/report/20261027T151646Z-776f29cf/summary.json) | 3.999 | 0.000 | Not required |
| Link failure | RF + loss guard | [`20261027T151725Z-f6caa845`](../evidence/runs/report/20261027T151725Z-f6caa845/summary.json) | 3.764 | 5.864 | 8.022 |
| Congestion | RF + loss guard | [`20261027T151807Z-9c06ddef`](../evidence/runs/report/20261027T151807Z-9c06ddef/summary.json) | 3.886 | 2.807 | 4.976 |
| Increased delay | RF + loss guard | [`20261027T151849Z-811520ad`](../evidence/runs/report/20261027T151849Z-811520ad/summary.json) | 3.998 | 0.008 | 3.325 |
| Both paths down | RF + loss guard | [`20261027T151928Z-180225f4`](../evidence/runs/report/20261027T151928Z-180225f4/summary.json) | 1.999 | 50.016 | No alternative |

These rows predate automatic failback. Use `--no-failback` for comparable new
experiments. A different timing on another run is not a failure by itself.
The RF-only loss result demonstrates a missed fault in this recording; it is
not an accuracy estimate or a general ranking.

## Later automatic-return examples

These 28 October 2026 runs use six switches, 4 Mbps load, 10 Mbps capacity and
enabled failback. They are additional evidence, not replacements for the report
tables. Their source hash matches the current controller files.

| Scenario | Run ID | Verified recovery s | Fault clearance to primary return s | Failovers | Automatic returns |
| --- | --- | ---: | ---: | ---: | ---: |
| Link failure | [`20261028T031343Z-9deb6c3e`](../evidence/runs/failback/20261028T031343Z-9deb6c3e/summary.json) | 8.017 | 5.362 | 1 | 1 |
| Link failure | [`20261028T041720Z-9547e8cb`](../evidence/runs/failback/20261028T041720Z-9547e8cb/summary.json) | 8.026 | 6.443 | 1 | 1 |
| Packet loss | [`20261028T041814Z-cf7bae53`](../evidence/runs/failback/20261028T041814Z-cf7bae53/summary.json) | 3.217 | 6.364 | 1 | 1 |

The timeline screenshot corresponds to `20261028T031343Z-9deb6c3e`: it shows fault
onset, backup routing, verified application recovery, fault clearance and
`primary_restored`. The other two rows are later saved examples of the same
feature, not trials freshly rerun during submission packaging.

## Additional dashboard stress screenshot

`20261027T191045Z-3101b8ae` used 10 Mbps offered application load on 10 Mbps links
with no injected fault. Its screenshot records high utilization, transient probe
loss and several route changes. This is a separate stress example and is not
one of the report's 4 Mbps measurements. Do not use it as evidence of fault
recovery or as the report's normal-operation baseline.

## Automated verification during packaging

The recorded [unit-test output](../evidence/verification/unit-tests.txt) reports
**18 passing tests**. They cover policy decisions, healthy-window and elapsed-time
requirements, reset after unhealthy observations, disabled failback, active-backup
failure, both-path failure, CLI/dashboard propagation and metric accounting.
These are automated policy/configuration/accounting checks, not a live Mininet
integration test.

The [doctor output](../evidence/verification/doctor.txt) confirms required binaries,
modules and model checksum availability on the lab machine. It explicitly does
not verify a live network. The evidence restore utility was checked in a temporary
directory: 12 runs restored, an identical repeat skipped all files, and a modified
local record was rejected without overwrite. See [restore-check.txt](../evidence/verification/restore-check.txt).

[verification.json](../evidence/verification/verification.json) records time,
environment, package versions, controller hash and check scope. A fresh live
smoke test was not rerun during packaging because sudo requires interactive
authentication. Run `sudo python3 main.py smoke` before evaluation.

A separate clean clone of committed revision `f566fce` passed all 18 tests,
restored all 12 included recordings, and served the dashboard and history API
without the local `.venv` or administrator access. See
[clean-clone.txt](../evidence/verification/clean-clone.txt). This verifies the
saved-results workflow; it does not verify a fresh install of the live-network
dependencies on another machine.

## Raw evidence format

| File | Meaning |
| --- | --- |
| `metadata.json` | Configuration, status, environment, timestamps and source/model hashes |
| `samples.csv` | Path observations and controller decisions during traffic |
| `events.jsonl` | Actual fault and route-change times |
| `application-iperf.json` | Raw application UDP transfer and receiver information |
| `summary.json` | Computed whole-run and recovery metrics |
| `cnS*-flows.txt` | Final per-switch OpenFlow entries |
| `*-server.json`, `background-iperf.json` | Supporting traffic-process output, where present |

[evidence/results.csv](../evidence/results.csv) collects the same metrics for
all 12 selected runs. [manifest.json](../evidence/manifest.json) records byte
counts and SHA-256 checksums for every original run file. CSV and raw JSON are
the numerical evidence; screenshots illustrate the interface.

Recovery requires two healthy application probe windows after rerouting while
the injected fault is active. Per-path ping loss is distinct from whole-run
receiver-side UDP loss. A route change alone is insufficient. Exact timing and
NetEm loss are variable, so these observations do not establish general
reliability, model accuracy or consistent superiority between methods.
