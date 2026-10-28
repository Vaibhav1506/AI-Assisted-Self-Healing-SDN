"""Human-readable terminal presentation; measurements and policy remain separate."""

import os
import shutil
import sys

_live_rows = 0


def clear_live():
    """Erase the temporary panel before printing a permanent event or error."""
    global _live_rows
    if _live_rows:
        sys.stdout.write(f"\x1b[{_live_rows}A\r\x1b[J")
        sys.stdout.flush()
        _live_rows = 0


def live_panel(lines):
    global _live_rows
    interactive = sys.stdout.isatty() and os.environ.get("TERM") != "dumb"
    if interactive:
        clear_live()
        # Keep each row narrower than the terminal so cursor movement stays valid.
        width = max(1, shutil.get_terminal_size().columns - 1)
        lines = [line[:width] for line in lines]
        sys.stdout.write("\r" + "\n".join(lines) + "\n")
        sys.stdout.flush()
        _live_rows = len(lines)
    else:
        print("\n".join(lines), flush=True)


def number(value, unit="", digits=3):
    return "not observed" if value is None else f"{value:.{digits}f}{unit}"


def configuration(config):
    method = config.get("method", config["mode"])
    names = {"rf_without_loss_guard": "Random Forest + 15% measured-loss safeguard",
             "rf_without_loss": "Random Forest alone (no loss safeguard)",
             "threshold": "Fixed thresholds"}
    print("\nEXPERIMENT CONFIGURATION")
    print(f"  Detector      : {names.get(method, method)} [{method}]")
    topology = config.get("topology", "diamond")
    print(f"  Topology      : {topology} ({6 if topology == 'long_diamond' else 4} switches)")
    print(f"  Scenario      : {config['scenario']}")
    print(f"  Application   : {config['load_mbps']:g} Mbps UDP; branch capacity {config['capacity_mbps']:g} Mbps")
    descriptions = {
        "normal": "No injected impairment",
        "loss": f"{config['loss_pct']:g}% configured link loss in each direction",
        "delay": f"Impaired-link delay set to {config['delay_ms']:g} ms in each direction",
        "congestion": f"{config['background_mbps']:g} Mbps additional offered background traffic",
        "link_down": "Disconnect a link on the selected branch",
        "both_down": "Disconnect links on BOTH branches; no usable alternative"}
    print(f"  Impairment    : {descriptions[config['scenario']]}")
    if config['scenario'] != 'normal':
        print(f"  Fault target  : {'both branches' if config['scenario'] == 'both_down' else config['fault_path']}")
        print(f"  Planned fault : {config['fault_start']:g}–{config['fault_end']:g} s (actual times shown in events)")
    print(f"  Traffic time  : {config['duration']:g} s, plus setup and cleanup")
    print(f"  Confirmation  : {config['confirmations']} unhealthy observations; hold-down {config['hold_down']:g} s; hard link failures bypass both")
    if config.get('failback', False):
        print(f"  Auto failback : enabled; primary healthy for {config.get('failback_delay', 5):g} s and "
              f"{config.get('failback_confirmations', 3)} consecutive observations")
        print("                  Requires links up, 0% probe loss, RTT <40 ms, utilization <90%, and detector approval")
    else:
        print("  Auto failback : disabled; retain the active route while healthy")
    if method == 'threshold':
        print("  Rules         : loss >=15%, RTT >=40 ms, missing RTT, or utilization >=90%")
    print("  Recovery check: two healthy post-switch endpoint probe windows while fault persists")
    print("                  Healthy window = 0% probe loss and average RTT <40 ms", flush=True)


def event_line(value):
    clear_live()
    kind = value['event']
    if kind == 'started':
        detail = f"Traffic started on {value['path']}"
    elif kind in ('fault_on', 'fault_off'):
        target = 'both branches' if value['scenario'] == 'both_down' else value['path']
        detail = f"{value['scenario']} on {target}: {'APPLIED' if kind == 'fault_on' else 'REMOVED'}"
    elif kind == 'route_change':
        label = "Primary restored | " if value.get('reason') == 'primary_restored' else ""
        detail = (f"{label}{value['source']} -> {value['destination']} | reason={value['reason']} | "
                  f"rule installation {value['install_s'] * 1000:.2f} ms")
    elif kind == 'completed':
        detail = "Traffic finished; calculating whole-run receiver results"
    else:
        detail = str({k: v for k, v in value.items() if k not in ('elapsed_s', 'event')})
    print(f"  [{value['elapsed_s']:6.2f} s] {kind.upper():12} {detail}", flush=True)


def measurement(elapsed, observations, app, decision, detector, current):
    lines = [f"  {elapsed:5.1f}s | active={current} | {decision}",
             "  Path    Link  Loss%  RTT(ms)  Util%  RF degraded/cutoff  Guard"]
    for path, obs in observations.items():
        assessment = "fixed rules"
        if hasattr(detector, 'probability'):
            guarded = hasattr(detector.estimator, 'loss_threshold')
            estimator = detector.estimator.estimator if guarded else detector.estimator
            raw = float(estimator.predict_proba([obs.features()])[0, detector.column])
            assessment = f"{raw:.0%}/{detector.artifact['threshold']:.0%}"
            assessment = f"{assessment:19} "
            assessment += ('ON' if obs.loss_pct >= detector.estimator.loss_threshold else 'clear') if guarded else 'off'
        rtt = f"{obs.rtt_ms:.1f}" if obs.rtt_ms is not None else "--"
        lines.append(f"  {path:7} {'UP' if obs.link_up else 'DOWN':4} {obs.loss_pct:5.1f}  {rtt:>7}  "
                     f"{obs.utilization * 100:5.1f}  {assessment}")
    lines.append(f"  Endpoint: probe loss {app['loss_pct']:.1f}% | RTT {number(app['rtt_ms'], ' ms')}")
    live_panel(lines)


def results(summary, config):
    print("\nRECOVERY RESULTS")
    print(f"  Route changes          : {summary['route_changes']}")
    if 'automatic_failbacks' in summary:
        print(f"  Failure-driven switches: {summary['failover_changes']}")
        print(f"  Automatic failbacks    : {summary['automatic_failbacks']}")
        print(f"  Fault clear to failback: {number(summary['fault_clear_to_failback_s'], ' s')}")
    print(f"  Fault onset            : {number(summary.get('fault_on_s'), ' s')}")
    print(f"  Fault to route change  : {number(summary['detection_and_actuation_s'], ' s')}")
    print(f"  Fault to verified recovery: {number(summary['verified_recovery_s'], ' s')}")
    print(f"  Recovery observed      : {'yes' if summary['recovery_observed'] else 'no'}")
    if config['scenario'] == 'normal':
        print("  Interpretation         : No fault injected; recovery is not required.")
    elif config['scenario'] == 'both_down':
        print("  Interpretation         : Both paths unavailable; restoration after fault removal is not rerouting recovery.")
    elif not summary['recovery_observed']:
        print("  Interpretation         : Recovery criterion not met; inspect decisions and probes below/in samples.csv.")
    print("\nAPPLICATION RESULTS — averaged over the entire traffic run")
    print(f"  Receiver throughput    : {number(summary['receiver_mbps'], ' Mbps')} (offered {config['load_mbps']:g} Mbps)")
    print(f"  UDP packet loss        : {number(summary['udp_loss_pct'], '%')}")
    print(f"  UDP jitter             : {number(summary.get('udp_jitter_ms'), ' ms', 6)} (arrival timing variation, not RTT)")
    print(f"  Received data          : {summary.get('received_bytes', 'not observed')} bytes")
    print(f"  Mean endpoint probe RTT: {number(summary.get('mean_probe_rtt_ms'), ' ms')}")
    print(f"  Mean endpoint probe loss: {number(summary.get('mean_probe_loss_pct'), '%')}")
    if config['scenario'] == 'loss':
        print(f"  Loss distinction       : {config['loss_pct']:g}% configured on the impaired link; UDP loss above covers the whole run.")
