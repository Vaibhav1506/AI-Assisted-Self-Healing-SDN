# Installation and execution

Run commands from the cloned repository directory. The project can be placed
in any directory; commands use repository-relative paths.

## Linux setup

The tested lab environment used Linux, Python 3.14.4, Mininet and Open vSwitch.
Live experiments need Linux network namespaces, Open vSwitch kernel support and
administrator access. Native Windows/macOS execution has not been verified;
a compatible Linux VM is an option.

For a Debian/Ubuntu-style system with these packages available:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip mininet \
  openvswitch-switch iperf3 iputils-ping iproute2
sudo systemctl start openvswitch-switch
```

Without systemd, use the system's service manager to start Open vSwitch.
Check that ovs-vsctl, ovs-ofctl, iperf3, ping, tc, ip, ss and mnexec are on PATH.

## Python environment

`main.py` uses `.venv/bin/python` under the repository root. Create this
machine-specific environment after cloning; it is not included in GitHub.

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
python3 main.py doctor
```

`--system-site-packages` exposes the system Mininet module inside the environment.
`doctor` must report all required binaries/modules and `trained_detector: ready`.
It checks availability only, not a running network.

Recorded package versions: numpy 2.3.5, scipy 1.18.1, scikit-learn 1.9.1,
joblib 1.5.2 and threadpoolctl 3.7.0. These match the lab machine. A clean install
on a second machine has not been verified. If pip reports an unavailable version
or unsupported interpreter, use a compatible environment before changing pins.
The serialized scikit-learn model may not work with another library version.

The required model is `src/selfheal/assets/detector.joblib`. Its SHA-256 is:

```text
5f3528e6490b50c7fc7e2a33f1556533ac5ebc00356a85f99235ae4458983001
```

The loader checks its checksum and feature schema. Keep it with the source.

## Checks and live rehearsal

```bash
python3 -B -m unittest discover -s tests -v
sudo python3 main.py smoke
```

The first checks policy/configuration/accounting without root. The second builds
a six-switch network, introduces a link failure, checks recovery on backup,
clears the fault and checks return to primary. It requests 22 seconds of traffic
plus setup/cleanup. Success prints `SMOKE PASSED`. It uses fixed thresholds,
not the RF detector.

## Dashboard and report settings

```bash
sudo python3 dashboard/server.py
```

Visit `http://127.0.0.1:8765`; add `--port 8766` if necessary. Run one experiment
at a time. Controls select topology, scenario, method, traffic, capacity and
return policy. Scenarios: normal operation, link failure, packet loss, congestion,
increased delay and both paths down.

The report uses six switches, 4 Mbps load, 10 Mbps links and disabled automatic
return. It was recorded before failback was added. Current defaults enable
return, which may change whole-run statistics.

## Restore saved recordings

```bash
python3 tools/restore_evidence.py
python3 reset_dashboard.py --restore
python3 dashboard/server.py
```

This requires no root and does not start a network. Select a recording in
**Run history**. The utility verifies checksums and skips identical files; it
refuses to overwrite different existing evidence. Use `--group report`,
`--group failback` or `--group additional` for a single set. Refresh the browser
with Ctrl+Shift+R after clearing the dashboard display cutoff.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Missing `.venv/bin/python` | Create the environment at the repository root. |
| Missing `mininet` module | Verify system Mininet; recreate `.venv` with `--system-site-packages`. |
| Open vSwitch unavailable | Start its service and inspect `sudo ovs-vsctl show`. |
| Live controls disabled | Restart the dashboard with sudo. |
| Another demo is running | Wait, or stop it using the runner that started it. |
| Reserved `cnS*` bridges exist | Check for an active experiment before diagnosing stale resources; preserve unrelated networks. |
| Empty history | Restore recordings and clear the display cutoff. |
| Missing comparison | Match topology, scenario, load, capacity and return-policy settings. |
| Model checksum fails | Restore the committed model; investigate the changed artifact before loading it. |

See [DEMO_GUIDE.md](../DEMO_GUIDE.md) for demonstration details. New runs go to
`.runtime/runs/`.
