# AI Assisted Self Healing SDN

**BCSE308P Computer Networks Lab · Team 5 · Slot L13 + L14**  
Vaibhav Bakshi · 24BCE2052

A Mininet network with primary and backup paths. A Python controller detects
link failure, packet loss, delay or congestion and reroutes traffic through
Open vSwitch using OpenFlow 1.3. The dashboard shows telemetry, recovery events
and recorded experiments.

## Download files

- [L13_L14_Team5_SourceCode.zip](L13_L14_Team5_SourceCode.zip): project source,
  fitted model, configuration, tests, raw recordings, report and presentation PDFs.
- [L13_L14_Team5_Screenshots.zip](L13_L14_Team5_Screenshots.zip): four dashboard
  captures showing healthy operation, failover, recovery and return to primary.

This README is provided separately. Extract both ZIPs into the same location;
their contents combine into one `L13_L14_Team5/` project folder.

## Requirements and installation

Live experiments require Linux or a Linux VM with administrator access, Python 3,
Mininet, Open vSwitch, iperf3, ping and iproute2 (`ip`, `tc`, `ss`).

On Debian/Ubuntu-style Linux:

```bash
sudo apt-get update
sudo apt-get install -y git unzip python3 python3-venv python3-pip mininet \
  openvswitch-switch iperf3 iputils-ping iproute2
sudo systemctl start openvswitch-switch
```

Clone the repository, extract the two ZIPs and enter the extracted project:

```bash
git clone https://github.com/Vaibhav1506/AI-Assisted-Self-Healing-SDN.git
cd AI-Assisted-Self-Healing-SDN
unzip L13_L14_Team5_SourceCode.zip
unzip L13_L14_Team5_Screenshots.zip
cd L13_L14_Team5
```

If you downloaded the ZIPs directly, open a terminal in their download folder
and start with the two `unzip` commands above.

Create the Python environment inside the extracted folder:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
python3 main.py doctor
```

`--system-site-packages` exposes the installed Mininet module to `.venv`.
The lab used Python **3.14.4** and the pins in `requirements.txt`; a fresh
installation on another machine has not been verified. Keep
`src/selfheal/assets/detector.joblib` in place. `doctor` checks dependencies and
the model checksum and should report `trained_detector: ready`.

## Run the project

Run all following commands from the extracted `L13_L14_Team5/` folder:

```bash
sudo python3 dashboard/server.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765), choose a scenario and detector,
then select **Run experiment**. Defaults: six switches, 4 Mbps traffic and
10 Mbps links. Stop the server with Ctrl+C.

Command-line options:

```bash
sudo python3 main.py demo
sudo python3 main.py demo --scenario link_down
sudo python3 main.py smoke   # Live failover and failback check
python3 main.py show         # Latest saved result
```

## Replay saved experiments

To view the 12 included recordings without administrator access:

```bash
python3 tools/restore_evidence.py
python3 reset_dashboard.py --restore
python3 dashboard/server.py
```

Open **Run history** in the dashboard. New live experiments require the setup
and administrator access described above.

## Expected results

- Healthy traffic stays on the primary path under the default load.
- A primary-path fault triggers rerouting to a healthy backup. Two healthy
  application probe windows verify recovery after switching.
- With automatic return enabled, traffic returns after five seconds of sustained
  primary health and at least three healthy observations.
- With both paths down, the controller reports no healthy alternative.

Measured results and logs are inside `evidence/`; timings vary between runs.
The four screenshots in `evidence/screenshots/` replay measured run
`20261028T041720Z-9547e8cb` at 8 s, 13 s, 22 s and completion.

## Tests and documents

```bash
python3 -B -m unittest discover -s tests -v
```

These 18 policy, configuration and metric checks need neither root nor Mininet.
The extracted project also contains `L13_L14_Team5_Report.pdf` and
`L13_L14_Team5_PPT.pdf`. New runs are written to `.runtime/` inside that folder.
