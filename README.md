# AI Assisted Self Healing SDN

**BCSE308P Computer Networks Lab · Team 5 · Slot L13 + L14**  
Vaibhav Bakshi · 24BCE2052

Submission filename prefix: `L13_L14_Team5`.

This project uses **Mininet** to emulate a network with primary and backup paths.
A Python controller detects packet loss, delay, congestion or link failure using
Random Forest detection or fixed thresholds, then reroutes traffic through
**Open vSwitch** using OpenFlow 1.3. The dashboard displays measurements,
recovery events and recorded experiments.

## Requirements

- **Linux or a Linux VM**, with administrator access for live experiments.
- **Python 3**, `venv` and `pip` for the controller and its dependencies.
- **Mininet** to create virtual hosts, switches and links.
- **Open vSwitch** to apply forwarding rules.
- **iperf3**, **ping** and **iproute2** (`ip`, `tc`, `ss`) for traffic and measurements.

The lab used **Python 3.14.4** and the package versions in `requirements.txt`.
Those pins and the fitted model must be compatible with your Python environment;
a fresh dependency installation on another machine has not been verified.
The dashboard itself uses Python's standard library.

## Installation

On Debian/Ubuntu-style Linux, install the system packages and start Open vSwitch:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip mininet \
  openvswitch-switch iperf3 iputils-ping iproute2
sudo systemctl start openvswitch-switch
```

Clone the repository and create its Python environment:

```bash
git clone https://github.com/Vaibhav1506/AI-Assisted-Self-Healing-SDN.git
cd AI-Assisted-Self-Healing-SDN
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
python3 main.py doctor
```

`--system-site-packages` makes the system-installed Mininet module available in
`.venv`. Keep `src/selfheal/assets/detector.joblib` in place. The `doctor` command
checks dependencies and the model checksum; it should report
`trained_detector: ready`.

## Run the project

From the repository root:

```bash
sudo python3 dashboard/server.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765), choose the scenario and detector,
then select **Run experiment**. The default setup uses six switches, 4 Mbps
application traffic and 10 Mbps links. Automatic return to the primary path is
enabled after stable recovery. Stop the server with Ctrl+C.

Command-line alternatives:

```bash
sudo python3 main.py demo                 # Run the default experiment
sudo python3 main.py demo --scenario link_down
sudo python3 main.py smoke                # Live failover and failback check
python3 main.py show                      # Show the latest saved result
```

## Expected results

- **Healthy network:** under the default load, traffic stays on the primary path.
- **Primary-path fault:** traffic moves to a healthy backup; two healthy application
  probe windows verify recovery after rerouting.
- **Primary restored:** with automatic return enabled, traffic returns after five
  seconds of sustained primary health and at least three healthy observations.
- **Both paths down:** the controller reports no healthy alternative during the
  outage; recovery requires an available healthy path.

Measured timings are available in [recorded results](evidence/results.csv) and
vary between runs.

## Replay included recordings

To view the 12 saved experiments without administrator access:

```bash
python3 tools/restore_evidence.py
python3 reset_dashboard.py --restore
python3 dashboard/server.py
```

Open **Run history** in the dashboard. This mode supports recorded playback;
starting a new experiment requires the live setup above.

## Dashboard screenshots

These recorded-playback captures use [run `20261028T041720Z-9547e8cb`](evidence/runs/failback/20261028T041720Z-9547e8cb/summary.json):
six switches, RF + loss guard, 4 Mbps traffic and 10 Mbps links.

| Screenshot | Recorded stage |
| --- | --- |
| [Healthy primary](evidence/screenshots/L13_L14_Team5_Screenshot_01_Healthy_Primary.jpg) | At 8 s: primary selected, zero probe loss |
| [Fault and failover](evidence/screenshots/L13_L14_Team5_Screenshot_02_Fault_Failover.jpg) | At 13 s: link failure detected, backup selected |
| [Backup recovery](evidence/screenshots/L13_L14_Team5_Screenshot_03_Backup_Recovery.jpg) | At 22 s: healthy application probes and verified recovery |
| [Primary restored](evidence/screenshots/L13_L14_Team5_Screenshot_04_Primary_Restored.jpg) | Complete timeline, including fault clearance and automatic return |

## Tests and project files

Run the 18 policy, configuration and metric checks without root or Mininet:

```bash
python3 -B -m unittest discover -s tests -v
```

| Folder | Contents |
| --- | --- |
| `src/selfheal/` | Controller, topology, telemetry and fitted model |
| `dashboard/` | Local Python server and browser interface |
| `evidence/` | Original recordings, screenshots, checksums and [results](evidence/results.csv) |
| `tests/` | Automated checks |
| `tools/` | Saved-evidence restore utility |
| `documents/` | [Report PDF](documents/L13_L14_Team5_Report.pdf) and [presentation PDF](documents/L13_L14_Team5_PPT.pdf) |

Submission ZIPs in `documents/`: `L13_L14_Team5_SourceCode.zip` (complete project)
and `L13_L14_Team5_Screenshots.zip` (four dashboard captures). Extract the source
ZIP and run the setup commands from its `L13_L14_Team5/` folder.

New runs are saved under `.runtime/`. This directory and the local `.venv/`
environment are ignored by Git.
