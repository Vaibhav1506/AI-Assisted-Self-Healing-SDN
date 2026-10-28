# Self-healing SDN: explanation and demonstration guide

This guide describes the application currently in this folder. Commands were checked against its source and CLI help. Saved example measurements below are historical results from 20 October 2026; they are not fresh live tests.

## 1. What the project does

The project demonstrates automatic traffic rerouting in an emulated software-defined network. It builds two possible paths between a sender and a receiver, sends real UDP traffic, deliberately impairs the active path, measures both paths, and installs forwarding updates when a healthy alternative exists.

The useful behavior is maintaining communication through an alternative path without manually changing routes during the experiment. "Healing" means rerouting traffic around the impairment; it does not physically repair the failed link. The experiment runner separately removes the injected fault at its scheduled time.

SDN separates forwarding from the software that decides forwarding behavior. Here, Open vSwitch switches forward packets using OpenFlow 1.3 rules. A local Python control loop measures conditions, decides whether to change paths, and applies rules through `ovs-ofctl`. This implementation uses that local control loop rather than a separate Ryu or ONOS server.

## 2. Default network

The default topology has six switches and six hosts. The main application uses h1 and h2; b1 through b4 provide endpoints for background congestion traffic.

```text
                    cnS2 ----- cnS5
                   /               \
h1 ----------- cnS1                 cnS3 ----------- h2
                   \               /
                    cnS4 ----- cnS6
```

- Primary route: h1 -> cnS1 -> cnS2 -> cnS5 -> cnS3 -> h2.
- Backup route: h1 -> cnS1 -> cnS4 -> cnS6 -> cnS3 -> h2.
- h1 address: 10.77.0.1; h2 address: 10.77.0.2.
- Probe addresses 10.77.0.102 and 10.77.0.103 both belong to h2, with rules keeping their probes on the primary and backup paths respectively.
- Main offered UDP load: 4 Mbps; configured inter-switch link capacity: 10 Mbps.
- Primary inter-switch link delay: 2 ms per link; backup: 3 ms per link.
- In the six-switch topology, the usual primary fault location is the cnS5–cnS3 link. The corresponding backup link is cnS6–cnS3.
- The four-switch `diamond` option omits cnS5 and cnS6.

Mininet creates Linux network namespaces and virtual links. Open vSwitch forwards real packets, and Linux traffic control applies the configured bandwidth, delay, and loss. The network is emulated locally; it does not require physical switches.

## 3. Measurement and recovery cycle

1. Build the virtual network and install initial forwarding rules.
2. Check initial connectivity on both paths and to the application destination.
3. Start iperf3 UDP traffic from h1 to h2.
4. Repeatedly send five ping probes for each path and five to the application destination. The measurement interval target is one second; unavailable paths can make cycles take longer.
5. Extract measured packet loss, average RTT, and RTT standard deviation. Estimate utilization from transmit-byte counter deltas on the last inter-switch link of each path, using the larger direction. Also inspect inter-switch interface states along each path.
6. Evaluate the active path and the alternative using the selected detector.
7. For degradation, normally require two consecutive unhealthy observations and respect a five-second hold-down after a switch. A detected hard link failure bypasses those two waiting rules.
8. Select the other route only when it is considered healthy.
9. Modify and verify the application ingress forwarding rules. Commit the policy's new current path after successful installation.
10. While on a healthy backup, monitor primary recovery. With automatic failback enabled (the default), require at least five seconds and three consecutive healthy primary observations before returning. A qualifying observation has links up, zero probe loss, RTT below 40 ms, utilization below 90%, and detector approval. Any unhealthy observation resets the wait; the existing switch hold-down still applies.
11. Continue measuring, save the experiment evidence, and clean up the virtual network.

Failback records a `route_change` with reason `primary_restored`; the dashboard labels it **Primary restored**. Use `--no-failback` or the dashboard's **Return to primary** setting to retain the healthy backup instead. Configure the wait and observation count with `--failback-delay` and `--failback-confirmations`, or the corresponding dashboard fields. A hard failure on the active backup bypasses the failback wait when the primary is a healthy alternative. If both paths are unhealthy, the policy reports `no_healthy_alternative`.

## 4. Three detector methods

| CLI method | Behavior |
|---|---|
| `rf_without_loss_guard` | Default: the bundled Random Forest plus a measured-loss safeguard that marks a path unhealthy at loss >= 15%. Despite the name, this option includes the guard. |
| `rf_without_loss` | The same forest without that loss safeguard. |
| `threshold` | Fixed rules: loss >= 15%, missing RTT, RTT >= 40 ms, or utilization >= 90%. |

The forest uses four features in this order: loss percentage, RTT, RTT standard deviation, and utilization. It has 200 trees and marks a sample degraded when its predicted degraded probability is at least 0.65. Missing RTT is represented as 1000 ms for inference. The link-state check is separate from the four ML features.

The bundled forest was fitted beforehand. Running a demo loads it; it does not retrain it. Its training report excludes the dedicated loss-injection scenario, although measured loss is still an input feature. The guarded/unguarded comparison illustrates the benefit of the explicit safeguard on that excluded fault family.

## 5. Preparation

Use a Linux terminal and the exact existing project directory:

```bash
cd /path/to/L13_L14_Team5
python3 main.py doctor
```

Check that required binary paths are present, module checks are true, and `trained_detector` is `ready`. The doctor's `live_network_verified: false` means it performs availability checks only.

`main.py` automatically selects the project's `.venv`; environment activation is unnecessary. The existing dependencies and trained model are local. This demo does not need an online service.

Use `sudo` for live experiments because Mininet needs to create interfaces, namespaces, and traffic-control rules. Enter your Linux password when prompted; password characters are not displayed. Run one experiment at a time and keep the terminal open until it finishes.

## 6. Quick rehearsal: live link failure

```bash
sudo python3 main.py smoke
```

This uses the six-switch topology, the threshold detector, and a link-down fault. It requests 22 seconds of application traffic, with the fault introduced around second 3 and cleared around second 11, plus network setup and cleanup time. The remaining traffic time allows the primary stability wait and automatic return.

Success prints:

```text
SMOKE PASSED: injected link failure, verified failover recovery, returned to primary.
```

The smoke command checks for two route changes: one failure-driven switch and one automatic failback after fault clearance, plus verified application recovery while the fault persists. It does not evaluate the ML detector.

## 7. Main presentation demo: guarded ML with packet loss

```bash
sudo python3 main.py
```

Equivalent explicit command:

```bash
sudo python3 main.py demo --method rf_without_loss_guard --topology long_diamond --scenario loss --load 4
```

| Approximate traffic time | Action |
|---|---|
| 0–10 seconds | Healthy operation using the primary route. |
| Around 10 seconds | Apply 20% loss on each direction of the selected primary-path link. |
| Following measurements | If the backup is healthy and confirmation requirements are met, switch application traffic to it. |
| Around 26 seconds | The experiment runner removes the injected loss. |
| Following healthy primary measurements | After at least five seconds and three consecutive healthy observations, return to primary if its probes and detector assessment remain healthy. |
| Around 36 seconds | Traffic ends; results are summarized and the virtual network is cleaned up. |

The 20% configured loss is a link-level impairment. Measured path probe loss and whole-run application packet loss are different measurements and need not equal 20%.

Point out `fault_on`, the failure-driven `route_change`, `fault_off`, the return with reason `primary_restored`, and `COMPLETE` in the terminal. Distinguish failover recovery during the fault from the later preferred-path return. Exact event times and measured outcomes vary across runs.

After completion, display the newest attempt again with:

```bash
python3 main.py show
```

## 8. What the printed results mean

| Output | Meaning |
|---|---|
| `Status: complete` | Execution and result generation completed. It does not alone mean successful recovery. |
| `Route changes` | Number of recorded application path changes. |
| `Failure-driven switches` | Path changes triggered by hard failure or measured degradation. |
| `Automatic failbacks` | Planned returns to primary after sustained healthy measurements. These are excluded from unnecessary reroutes. |
| `Fault clear to failback` | Time from actual `fault_off` to an automatic return after clearance; unobserved if no such return occurs. |
| `Fault to route change` | Elapsed time from actual `fault_on` to the relevant successful route-change event. Includes detection and actuation. |
| `Verified recovery` | Time from fault onset to the second consecutive healthy post-switch application-destination probe window while the fault persists. |
| `Recovery observed` | Whether that recovery criterion was met. |
| `Receiver throughput` | Receiver-side iperf throughput averaged over the application run. |
| `Application packet loss` | Receiver-side UDP packet loss over the application run. |

A healthy application-destination probe window means zero observed ping loss and average RTT below 40 ms. The probe-based recovery criterion and UDP receiver statistics are separate evidence. Recovery time is not simply OpenFlow installation time, and a route-change event by itself does not establish recovery.

Historical example from run `20261020T193803Z-a3e14986`, recorded on 20 October 2026:

```text
Detector: rf_without_loss_guard | Topology: long_diamond | Scenario: loss
Route changes: 1
Fault to route change: 1.576 s
Verified recovery: 3.228 s
Recovery observed: yes
Receiver throughput: 3.965 Mbps
Application packet loss: 0.845 %
```

These are saved measured results, not guaranteed values for a new run.

## 9. Demonstrate each scenario

Run these individually, waiting for completion between commands:

```bash
# Healthy operation: normally no reroute is needed
sudo python3 main.py demo --scenario normal

# Physical link state failure on the primary branch
sudo python3 main.py demo --scenario link_down

# Packet loss with the default guard
sudo python3 main.py demo --scenario loss

# Additional traffic offered at 12 Mbps to a 10 Mbps branch
sudo python3 main.py demo --scenario congestion

# Delay with explicit RTT-based threshold detection
sudo python3 main.py demo --method threshold --scenario delay

# Both branches disconnected: no healthy alternative during the fault
sudo python3 main.py demo --scenario both_down
```

For `normal`, `Recovery observed: no` and unobserved recovery timing are expected because there was no fault to recover from. For `both_down`, no alternative exists while both branches are down; connectivity can return after the runner clears the fault. That is different from successful rerouting during the fault.

Delay is shown with `threshold` because the diagnosis found synthetic delay-only inputs that the default ML model classified as healthy. A live default-ML delay evaluation is a separate experiment, not a guaranteed success.

## 10. Compare methods and topologies

Use the same scenario, offered load, and topology when comparing methods:

```bash
sudo python3 main.py demo --method rf_without_loss --scenario loss
sudo python3 main.py demo --method rf_without_loss_guard --scenario loss
sudo python3 main.py demo --method threshold --scenario loss
```

Compare recovery observed, recovery timing, whole-run receiver throughput, and UDP loss. One saved unguarded loss run did not reroute, while saved guarded loss runs did recover. This is evidence from those runs; repeated trials are needed to estimate consistent performance. The unguarded option still runs a detector and should not be called a static or no-controller baseline.

Show topology support with:

```bash
sudo python3 main.py demo --topology diamond
sudo python3 main.py demo --topology long_diamond
```

Both commands keep the default guarded loss demonstration. `diamond` has four switches; `long_diamond` has six.

An optional offered-load example is:

```bash
sudo python3 main.py demo --scenario loss --load 6
```

`--load` changes application Mbps. Set inter-switch capacity independently with `--capacity`, for example `sudo python3 main.py demo --capacity 20 --load 4`. Capacity must be greater than 0 and at most 100 Mbps, and defaults to 10. Dashboard Experiment and Compare methods expose the same setting. Congestion background load scales to 1.2 times capacity. Compare methods only at matching capacities; the existing presentation results use 10 Mbps and 4 Mbps application load. Capacity changes do not retrain the forest. The public CLI exposes method, topology, scenario, load, and capacity; it does not expose a training command, static baseline, duration flag, or interactive Mininet prompt.

## 11. Show actual OpenFlow rules while the demo runs

Keep the running demonstration in terminal 1. Once its virtual switches exist, use terminal 2:

```bash
sudo ovs-ofctl --no-names -O OpenFlow13 show cnS1
sudo ovs-ofctl --no-names -O OpenFlow13 dump-flows cnS1 'ip,nw_src=10.77.0.1,nw_dst=10.77.0.2'
```

The first command shows port mappings. The second filters the main forward application flow. Run the second command before and after `route_change` and compare `actions=output:...`.

For this topology's construction, cnS1 port 2 leads to cnS2 and port 3 to cnS4; verify with `show cnS1`. The main flow should initially use output 2 and use output 3 after switching to the backup route. Focus on the application destination 10.77.0.2, since the probe flows intentionally stay on their own paths.

For automatic refresh, optionally run:

```bash
sudo watch -n 1 "ovs-ofctl --no-names -O OpenFlow13 dump-flows cnS1 'ip,nw_src=10.77.0.1,nw_dst=10.77.0.2'"
```

Press Ctrl+C in terminal 2 to stop watching. After the experiment finishes, the virtual switches are removed, so live inspection commands then fail normally. Use the saved snapshots for later explanation. The saved `*-flows.txt` snapshots are overwritten by the final snapshot; they are not a before-and-after snapshot pair.

## 12. Show saved evidence

The terminal prints a unique `.runtime/runs/<run-id>/` directory for each attempt. `.runtime` is hidden; press Ctrl+H in the file manager to show hidden folders.

| File | Evidence |
|---|---|
| `metadata.json` | Configuration, completion/failure state, timestamps, environment and source/model fingerprints. |
| `events.jsonl` | Started, fault onset, route changes, fault clearance, completion. |
| `samples.csv` | Two path rows per measurement cycle, measured features, interface state, active/next route and decision reason. Application probe fields are duplicated across the two path rows. |
| `summary.json` | Aggregate recovery and traffic metrics. |
| `application-iperf.json` | Raw application traffic results, including server output. |
| `h2-server.json` | Receiver server output. |
| `cnS1-flows.txt` and other switch files | Final OpenFlow snapshots for the attempt. |
| `background-iperf.json` | Background traffic output when congestion traffic is used. |

To inspect the newest run in a terminal after it finishes:

```bash
DEMO_RUN_DIR="$(ls -d .runtime/runs/*/ | sort | tail -n 1)"
cat "$DEMO_RUN_DIR/events.jsonl"
cat "$DEMO_RUN_DIR/summary.json"
head -n 5 "$DEMO_RUN_DIR/samples.csv"
cat "$DEMO_RUN_DIR/cnS1-flows.txt"
```

You can open `samples.csv` in a spreadsheet application. `show` always selects the newest attempt, including a failed attempt; it does not select the latest successful attempt. Preserve the printed directory name when comparing runs.

## 13. Presentation order and speaking notes

For a concise demonstration:

1. Open the PPT and show the problem and topology.
2. Run `doctor` to show availability.
3. Run the main guarded loss demo and point out fault onset and automatic route change.
4. Explain recovery timing and receiver-side traffic statistics.
5. Open `events.jsonl`, `samples.csv`, and a switch flow snapshot as implementation evidence.
6. If time allows, run unguarded loss followed by guarded loss, keeping settings equal.
7. Use `both_down` to explain the limit imposed by having no healthy alternative.

Run the smoke test as rehearsal before presenting. Each standard demo requests 36 seconds of traffic plus setup and cleanup; budget additional time for your explanation.

Suggested introduction:

> Our project demonstrates a self-healing software-defined network. Two routes connect a sender and receiver. We continuously monitor path conditions while sending real traffic. When the active route degrades or fails, our controller checks the alternative and changes OpenFlow forwarding rules. We then verify endpoint probe recovery and measure receiver throughput and packet loss.

During fault injection:

> We are deliberately introducing packet loss on the primary route. The controller must detect the measured degradation, confirm it, check that the backup is healthy, and reroute the application while the fault is still present.

At the result:

> This event records the route change. This separate recovery measurement checks two healthy endpoint probe windows after the switch. The throughput and packet-loss values come from receiver-side application traffic measurements across the run.

If both paths are down:

> Automatic rerouting requires a usable alternative. During this fault both routes are disconnected, so the policy correctly has no healthy alternative.

## 14. Open the presentation and report

From the project directory:

```bash
xdg-open "Deliverables/Self_Healing_SDN_Presentation.pptx"
xdg-open "Deliverables/Self_Healing_SDN_Report.docx"
```

Use your presentation application's slideshow mode for the PPT. The named report and PPT in Deliverables/ use eight saved runs at 10 Mbps. Their raw records are in evidence/runs/report/. Later failback examples are separate. The report certificate signature still needs to be supplied before VTOP upload.

## 15. Explain the implementation files

| File | Role |
|---|---|
| `main.py` | Selects the existing Python environment and launches the CLI. |
| `src/selfheal/cli.py` | Commands, doctor, run locking, smoke verification, result display. |
| `src/selfheal/config.py` | Experiment defaults and validation. |
| `src/selfheal/network.py` | Mininet network, explicit OpenFlow rules, impairment injection, cleanup. |
| `src/selfheal/topology.py` | Four-/six-switch topology support and method/config consistency. |
| `src/selfheal/telemetry.py` | Probes, link status and byte-counter-based utilization. |
| `src/selfheal/core.py` | Observations, threshold detector and shared recovery policy. |
| `src/selfheal/learning.py` | Model integrity, loading, inference and loss guard. |
| `src/selfheal/experiment.py` | Traffic orchestration, event/sample persistence and result calculation. |
| `src/selfheal/parsers.py` | Parses ping, OpenFlow port counters and iperf output. |
| `src/selfheal/assets/detector.joblib` | Bundled fitted Random Forest artifact. |

## 16. Claims and limitations to explain accurately

- The default is a hybrid of ML prediction and a fixed loss safeguard.
- The controller detects current measured conditions. This demo does not establish advance failure prediction.
- It changes traffic routes; it does not repair hardware.
- It verifies a specific probe-based recovery criterion and reports UDP traffic statistics separately.
- Switching modifies two ingress switches sequentially, rather than as an atomic transaction across switches.
- The detector can miss some delay-only synthetic inputs; use the threshold delay demonstration for an explicit RTT rule.
- Use the bundled detector's stored metadata when explaining its original validation. Historical accuracy figures are not fresh measurements of this live demo.
- The bundled artifact contains its own stored held-out validation report. Stored training metrics do not establish general accuracy across all topologies and scenarios.
- Original historical training datasets and campaign tools are absent, so this folder cannot reproduce all historical report tables or retrain the original study through its public CLI.
- A completed run without recovery can be correct for `normal`, `both_down`, or an unguarded comparison. Judge the outcome against the scenario.

## 17. Troubleshooting

| Message or observation | Action |
|---|---|
| Administrator access required | Run the live command with `sudo`. |
| Doctor reports a missing dependency or damaged model | Resolve the reported item before a live demo; do not replace the detector with an arbitrary file because it is checksum-verified. |
| `Another project demo is running` | Wait for the existing experiment or stop it gracefully before starting another. |
| Project bridges already exist | Check for a running experiment first; inspect `sudo ovs-vsctl list-br`. Diagnose stale resources before removing anything. |
| `Recovery observed: no` | Check scenario, method, event log, and measurements; absence of a usable backup or missed detection can explain it. |
| A live switch command fails after completion | Expected after cleanup; inspect saved flow snapshots. |
| `show` displays a failure | It shows the newest attempt; inspect that run's metadata and error. |
| VS Code F5 targets a C++ program | The current editor launch configuration is stale. Use the terminal commands above. |

Ctrl+C in the experiment terminal requests cleanup. The environment diagnosis also found a missing `charset-normalizer` dependency of a system `python-debian` package inherited by the virtual environment. The application's pinned package versions, imports, and offline model inference passed despite that separate warning.

A fresh live test was not run during the diagnosis because sudo required interactive authentication. Perform the rehearsal on the demonstration machine before presenting.
