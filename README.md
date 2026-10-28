# AI Assisted Self Healing SDN

**BCSE308P Computer Networks Lab · Team 5 · Slot L13 + L14**  
Vaibhav Bakshi · 24BCE2052

This project detects path degradation in a Mininet network and moves application
traffic to a healthy backup path. A Python control loop measures packet loss,
round trip time, RTT variation and link utilization. Open vSwitch applies the
forwarding changes through OpenFlow 1.3. A local dashboard shows the topology,
measurements, event timeline, recorded playback and downloadable evidence.

The application supports four- and six-switch topologies, six fault scenarios,
three detection methods, configurable traffic and link capacity, and automatic
return to the primary path after stable recovery.

## Submission files

The prefix `L13_L14_Team5` represents slot **L13 + L14**, Team **5**.

| VTOP assignment | File or submission |
| --- | --- |
| 8 — Project report | [L13_L14_Team5_Report.pdf](Deliverables/L13_L14_Team5_Report.pdf) |
| 9 — Presentation | [L13_L14_Team5_PPT.pptx](Deliverables/L13_L14_Team5_PPT.pptx) |
| 10 — Repository | The URL of this GitHub repository |

The editable report is `Deliverables/L13_L14_Team5_Report.docx`.
**The certificate signature on report page 3 still needs to be supplied before
final VTOP report upload.** See the [submission checklist](docs/SUBMISSION_CHECKLIST.md).

## Repository contents

```text
main.py                      Application entry point
src/selfheal/                Controller, topology, telemetry and experiments
src/selfheal/assets/         Required fitted detector.joblib model
dashboard/                   Local server and browser interface
tests/                       Policy, accounting and configuration checks
tools/                       Saved-evidence restore utility
docs/                        Installation, topology, results and submission guide
evidence/runs/report/        Eight runs used by the report and slides
evidence/runs/failback/      Later automatic-return demonstrations
evidence/runs/additional/    Separate 10 Mbps offered-load stress example
evidence/screenshots/        Dashboard captures and provenance
evidence/verification/      Recorded checks and environment information
Deliverables/                Named report PDF, editable report and presentation
requirements.txt             Exact package versions from the lab machine
DEMO_GUIDE.md                 Detailed demonstration and troubleshooting guide
```

The simulation is defined in Python in `network.py` and `topology.py`. This
project uses Mininet; it has no Cisco Packet Tracer `.pkt` file or database.
The source, trained model, configuration defaults, flow dumps and raw results
needed to inspect the implementation are included.

## Software requirements and installation

Live experiments require Linux or a Linux VM with administrator access,
Mininet, Open vSwitch, OpenFlow 1.3 support, iperf3, ping, ip, ss and tc.
The lab machine used Python **3.14.4** and the exact versions in
`requirements.txt`. The dashboard uses Python's standard library and needs no
Node.js, npm or external web service.

See [INSTALLATION.md](docs/INSTALLATION.md) for compatibility notes and
troubleshooting. Run these commands from the cloned repository directory:

```bash
git clone https://github.com/Vaibhav1506/L13_L14_Team5.git
cd L13_L14_Team5

# Debian/Ubuntu-style Linux, with the packages available in its repositories.
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip mininet \
  openvswitch-switch iperf3 iputils-ping iproute2
sudo systemctl start openvswitch-switch

# Make the system-installed Mininet module visible in the environment.
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
python3 main.py doctor
```

These package pins match the tested machine. A clean install on a second
machine has not yet been verified. If a Python/package combination is
unavailable, use a compatible Linux environment and validate the model before
changing versions. The trained model is a required trusted artifact; the
application checks its checksum before loading it.

## Execute the project

```bash
sudo python3 dashboard/server.py
```

Open **http://127.0.0.1:8765** and keep the terminal open. Choose a scenario and
press **Run experiment**. Use six switches, 4 Mbps application traffic and
10 Mbps capacity for the report's network settings. A standard experiment
requests 36 seconds of traffic plus setup and cleanup. Experiments run
sequentially. The server binds only to this computer. Ctrl+C requests cleanup
of its own experiment.

The command line runs the same controller:

```bash
python3 main.py doctor
sudo python3 main.py smoke
sudo python3 main.py demo
python3 main.py show
```

`doctor` checks dependency/model availability. `smoke` runs a 22-second
threshold-based link-failure test and checks verified failover and automatic
return to primary. It does not evaluate the RF model. `demo` defaults to
guarded RF, six switches and packet loss. `show` prints the latest saved attempt.

```bash
sudo python3 main.py demo --scenario link_down
sudo python3 main.py demo --method rf_without_loss
sudo python3 main.py demo --method threshold --scenario delay
sudo python3 main.py demo --topology diamond
sudo python3 main.py demo --capacity 20 --load 4
sudo python3 main.py demo --no-failback
```

The retained identifier `rf_without_loss_guard` means **RF plus the measured-loss
guard**. `rf_without_loss` means RF alone. The dashboard uses readable labels.
See [IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

## View saved evidence without administrator access

```bash
python3 tools/restore_evidence.py
python3 reset_dashboard.py --restore
python3 dashboard/server.py
```

Open **Run history** in the local dashboard. This mode cannot start a new network.
The utility verifies file checksums, copies records to `.runtime/runs/`, skips
identical files and refuses to overwrite a different existing record. Originals
remain under `evidence/`.

The report recordings predate automatic failback. To compare those packet-loss
methods, select **Stay on backup while healthy**, six switches, 4 Mbps load and
10 Mbps capacity. The comparison page uses the latest completed run with
matching settings, so check run IDs before quoting the report.

## Expected results

- Healthy operation needs no recovery. When both paths are down, there is no
  healthy alternative during the fault.
- The included guarded-RF recordings demonstrate recovery after link failure,
  packet loss, congestion and increased delay when the backup remains healthy.
- The original RF-only packet-loss run missed that fault. Guarded RF and fixed
  rules recovered in the recorded comparison.
- Automatic return defaults to five seconds of sustained primary health and
  three consecutive healthy observations. Links must be up, probe loss zero,
  RTT below 40 ms, utilization below 90%, and the detector must approve it.
  The switch hold-down also applies.

Recovery requires two healthy application probe windows after rerouting while
the fault persists. A route change alone does not establish recovery. Path-probe
loss differs from receiver-side UDP loss. Exact timings vary with scheduling and
NetEm loss; one run per condition cannot establish consistent performance.

The report and slides retain eight runs from **27 October 2026**, before
automatic failback was added. [TESTING_RESULTS.md](docs/TESTING_RESULTS.md)
identifies them separately from later failback examples. The original fitting
dataset and campaign tools are absent; the model supports inference, not
retraining or reproduction of historical training-accuracy claims.

## Automated checks

```bash
python3 -B -m unittest discover -s tests -v
```

These standard-library checks need neither root nor Mininet. They cover recovery
policy, stable failback, configuration propagation and metric accounting.
[Recorded verification](evidence/verification/) contains the actual output and
scope. Live integration testing requires the separate smoke command above.

New experiments write to ignored `.runtime/`. Virtual environments, caches,
document-build files and superseded reports stay outside the published source.
