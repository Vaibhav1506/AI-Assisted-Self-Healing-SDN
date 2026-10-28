# Network and implementation

## Topology and configuration

`src/selfheal/network.py` defines hosts, IPs, the four-switch diamond, links,
switch ports, forwarding rules and faults. `src/selfheal/topology.py` extends
both branches for six switches. `src/selfheal/config.py` contains defaults and
validation. The Mininet simulation is built from Python; it has no Packet
Tracer file or configuration database.

| Topology | Primary branch | Backup branch |
| --- | --- | --- |
| Four switches (`diamond`) | h1 → cnS1 → cnS2 → cnS3 → h2 | h1 → cnS1 → cnS4 → cnS3 → h2 |
| Six switches (`long_diamond`) | h1 → cnS1 → cnS2 → cnS5 → cnS3 → h2 | h1 → cnS1 → cnS4 → cnS6 → cnS3 → h2 |

Application hosts: h1 (`10.77.0.1`), h2 (`10.77.0.2`). Background hosts b1/b2
provide primary-branch congestion traffic; b3/b4 support the backup branch.
The dashboard draws h1/h2 and switches. Probe destinations keep both paths
observable. Default inter-switch capacity is 10 Mbps, with 4 Mbps application
load. Congestion demand is 1.2 times selected capacity.

## Controller and detectors

`telemetry.py` measures paths; `core.py` applies recovery policy; `learning.py`
loads RF. Feature order: loss percentage, RTT, RTT variation, utilization.
`experiment.py` starts traffic, injects/clears faults, applies decisions and
writes raw evidence before producing the summary. The controller uses local
`ovs-ofctl` commands for OpenFlow 1.3 updates.

| CLI identifier | Dashboard label | Behavior |
| --- | --- | --- |
| `rf_without_loss_guard` | Random Forest + loss guard | RF plus an override for measured loss of at least 15% |
| `rf_without_loss` | Random Forest only | Same RF without the loss override |
| `threshold` | Fixed thresholds | Limits on loss, RTT, utilization and missing replies |

The first identifier is a retained name; the code explicitly enables the guard
for it. All methods share routing policy. Hard link failures have a separate
link-state check.

## Return to primary

After failover, default automatic failback requires five seconds of continuous
primary health and three consecutive healthy observations. Links must be up,
probe loss zero, RTT below 40 ms, utilization below 90%, and the detector must
approve. An unhealthy observation restarts the wait; hold-down also applies.
A hard failure of the active backup can bypass the wait if primary is healthy.

The event reason is `primary_restored`, shown as **Primary restored**.
`failover_changes` and `automatic_failbacks` are separate.
`fault_clear_to_failback_s` measures actual clearance to planned return.
Planned returns do not count as unnecessary reroutes.

Report/slide recordings predate failback and retain their numerical results.
Later evidence documents this extension separately in [TESTING_RESULTS.md](TESTING_RESULTS.md).

## Interpretation and reproduction

Runs include metadata, probe CSV, timestamped events, receiver-side iperf data,
summary metrics and final OpenFlow dumps. Metadata records source/model hashes.
Historical records retain the fingerprint of their original code, which can
differ from the current source.

A route update is distinct from verified recovery: two healthy application
probe windows must follow rerouting while the fault persists. Whole-session
receiver UDP loss differs from per-path ping loss.

The detector is supplied for inference. Original fitting data/campaign tools
are absent, so this release does not reproduce training or independently
re-estimate validation accuracy. Results are single lab observations; scheduling
and NetEm loss are not deterministic even with the same experiment-group seed.
