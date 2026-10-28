"""Run real network experiments and persist raw observations before analysis."""
import csv
import hashlib
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import time
import uuid

from . import display
from .config import ExperimentConfig
from .core import RecoveryPolicy, ThresholdDetector
from .network import Laboratory, HOST_IPS
from .parsers import parse_iperf
from .telemetry import Monitor


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def source_fingerprint():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def release_ownership(directory):
    """Make root-created experiment artifacts editable by the invoking desktop user."""
    if os.geteuid() == 0 and "SUDO_UID" in os.environ and "SUDO_GID" in os.environ:
        uid, gid = int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
        for path in [Path(directory), *Path(directory).rglob("*")]:
            if not path.is_symlink():
                os.chown(path, uid, gid)


def run_experiment(config, output_root, model=None, purpose="evaluation"):
    config.validate()
    if purpose not in ("training", "evaluation", "smoke"):
        raise ValueError("Unknown experiment purpose")
    if config.mode == "ml":
        if model is None:
            raise ValueError("ML mode needs --model trained from real collection runs")
        from .learning import MLDetector
        detector = MLDetector(model, guard_loss=getattr(config, "method", "") == "rf_without_loss_guard")
    else:
        detector = ThresholdDetector()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = Path(output_root) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    metadata = {"run_id": run_id, "kind": "measured_mininet", "purpose": purpose,
                "status": "running", "config": asdict(config), "model": str(model) if model else None,
                "platform": platform.platform(), "python": platform.python_version(),
                "source_sha256": source_fingerprint(),
                "model_sha256": hashlib.sha256(Path(model).read_bytes()).hexdigest() if model else None,
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "seed_note": "Seed identifies an experiment group; kernel scheduling and NetEm loss are not deterministic."}
    write_json(directory / "metadata.json", metadata)
    print(f"RUN {run_id}: {config.mode}/{config.scenario}, load={config.load_mbps} Mbps", flush=True)
    display.configuration(asdict(config))
    if config.mode == "ml":
        print(f"  ML cutoff     : {detector.artifact['threshold']:.1%} predicted degradation probability", flush=True)
    print("\nLIVE EVENTS AND PROBES (probe loss differs from whole-run UDP loss)", flush=True)
    rows, events = [], []
    policy = RecoveryPolicy(detector, config.confirmations, config.hold_down,
                            failback=config.failback, failback_delay=config.failback_delay,
                            failback_confirmations=config.failback_confirmations)
    active_fault, last_event = False, float("-inf")
    try:
        with Laboratory(config) as lab:
            # Bind servers to their own namespace addresses; no host-network listeners.
            for host, port in (("h2", 5201), ("b2", 5202), ("b4", 5203)):
                server = lab.file_process(host, ["iperf3", "-s", "-B", HOST_IPS[host], "-p", str(port), "-J"],
                                          directory / f"{host}-server.json")
                deadline = time.monotonic() + 3
                while True:
                    if server.poll() is not None:
                        raise RuntimeError(f"iperf3 server failed on {host}; inspect server output")
                    listening = lab.host_command(host, ["ss", "-H", "-ltn"])
                    if f":{port}" in listening:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"iperf3 server on {host} did not become ready")
                    time.sleep(0.05)
            monitor = Monitor(lab)
            initial, app = monitor.measure()
            if any(not o.link_up or o.loss_pct > 0 for o in initial.values()) or app["loss_pct"] > 0:
                raise RuntimeError("Initial connectivity check failed; no experiment results will be reported")
            lab.snapshot(directory)
            client = lab.file_process("h1", ["iperf3", "-c", HOST_IPS["h2"], "-p", "5201", "-u",
                                       "-b", f"{config.load_mbps}M", "-t", str(math.ceil(config.duration)),
                                       "-i", "1", "-J", "--get-server-output"], directory / "application-iperf.json")
            start = time.monotonic()
            next_tick = 0.0
            background = None
            event_handle = open(directory / "events.jsonl", "w")
            with event_handle, open(directory / "samples.csv", "w", newline="") as samples:
                writer = None

                def event(kind, **values):
                    value = {"elapsed_s": time.monotonic() - start, "event": kind, **values}
                    events.append(value)
                    event_handle.write(json.dumps(value, allow_nan=False) + "\n")
                    event_handle.flush()
                    display.event_line(value)
                    return value["elapsed_s"]

                event("started", path=policy.current)
                while time.monotonic() - start < config.duration:
                    elapsed = time.monotonic() - start
                    desired_fault = config.scenario != "normal" and config.fault_start <= elapsed < config.fault_end
                    if desired_fault != active_fault:
                        lab.set_fault(desired_fault)
                        if config.scenario == "congestion":
                            if desired_fault:
                                source, destination, port = (("b1", "b2", 5202) if config.fault_path == "primary"
                                                             else ("b3", "b4", 5203))
                                background = lab.file_process(source,
                                    ["iperf3", "-c", HOST_IPS[destination], "-p", str(port), "-u",
                                     "-b", f"{config.background_mbps}M", "-t", str(math.ceil(config.duration)), "-J"],
                                    directory / "background-iperf.json")
                            elif background and background.poll() is None:
                                background.terminate()
                                background.wait(timeout=3)
                        active_fault = desired_fault
                        last_event = event("fault_on" if desired_fault else "fault_off",
                                           scenario=config.scenario, path=config.fault_path)
                    measured_at = time.monotonic() - start
                    observations, app = monitor.measure()
                    finished_at = time.monotonic() - start
                    path_before = policy.current
                    decision = policy.decide(observations, finished_at)
                    if config.mode == "static":
                        decision_reason = "static_no_recovery"
                    else:
                        decision_reason = decision.reason
                        if decision.destination:
                            install_start = time.monotonic()
                            lab.activate(decision.destination)
                            installed_at = time.monotonic() - start
                            policy.commit(decision, installed_at)
                            event("route_change", source=decision.source, destination=decision.destination,
                                  reason=decision.reason, install_s=time.monotonic() - install_start)
                    display.measurement(finished_at, observations, app, decision_reason, detector, path_before)
                    for path, observation in observations.items():
                        affected = active_fault and (config.scenario == "both_down" or path == config.fault_path)
                        row = {"run_id": run_id, "kind": "measured_mininet", "purpose": purpose,
                               "mode": config.mode, "scenario": config.scenario, "seed": config.seed,
                               "load_mbps": config.load_mbps, "elapsed_s": finished_at,
                               "probe_start_s": measured_at, "probe_duration_s": finished_at - measured_at,
                               **asdict(observation), "active_path": path_before,
                               "next_path": policy.current, "fault_active": active_fault,
                               "label": "degraded" if affected else "normal",
                               "transition": measured_at - last_event < 2.0,
                               "decision": decision_reason,
                               "app_loss_pct": app["loss_pct"], "app_rtt_ms": app["rtt_ms"]}
                        if writer is None:
                            writer = csv.DictWriter(samples, fieldnames=list(row))
                            writer.writeheader()
                        writer.writerow(row)
                        rows.append(row)
                    samples.flush()
                    if background and active_fault and background.poll() is not None:
                        raise RuntimeError("Congestion traffic stopped unexpectedly; inspect background output")
                    if client.poll() is not None and finished_at < config.duration - 1:
                        raise RuntimeError("Application traffic stopped early; inspect application output")
                    # Skip missed deadlines rather than producing bursts of catch-up samples.
                    next_tick = max(next_tick + config.interval,
                                    math.ceil((time.monotonic() - start) / config.interval) * config.interval)
                    time.sleep(max(0, start + next_tick - time.monotonic()))
                if active_fault:
                    lab.set_fault(False)
                client.wait(timeout=10)
                if client.returncode:
                    raise RuntimeError("Application traffic failed; inspect application-iperf.json")
                for handle in lab.handles:
                    handle.flush()
                traffic = parse_iperf(directory / "application-iperf.json")
                event("completed", **traffic)
            lab.snapshot(directory / "." )
        summary = summarize(config, rows, events, traffic)
        write_json(directory / "summary.json", {"run_id": run_id, "kind": "measured_mininet",
                                                 "purpose": purpose, "source_sha256": metadata["source_sha256"],
                                                 "model_sha256": metadata["model_sha256"], **asdict(config), **summary})
        metadata["status"] = "complete"
        print(f"COMPLETE {directory}", flush=True)
        return directory
    except BaseException as error:
        metadata["status"] = "failed"
        metadata["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        display.clear_live()
        metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
        write_json(directory / "metadata.json", metadata)
        release_ownership(directory)


def summarize(config, rows, events, traffic):
    # Application samples occur twice (once alongside each path); deduplicate them.
    app = [row for row in rows if row["path"] == "primary"]
    changes = [e for e in events if e["event"] == "route_change"]
    failbacks = [e for e in changes if e.get("reason") == "primary_restored"]
    fault = next((e for e in events if e["event"] == "fault_on"), None)
    clear = next((e for e in events if e["event"] == "fault_off"), None)
    fault_time = fault["elapsed_s"] if fault else None
    clear_time = clear["elapsed_s"] if clear else config.duration
    relevant = [e for e in changes if e.get("reason") != "primary_restored"
                and fault_time is not None and fault_time <= e["elapsed_s"] < clear_time
                and e["source"] == config.fault_path]
    first_change = relevant[0]["elapsed_s"] if relevant else None
    after_clear = [e for e in failbacks if clear is not None and e["elapsed_s"] >= clear_time]
    # Require two healthy application probe windows AFTER installation, while fault persists.
    recovery = None
    streak = 0
    if first_change is not None:
        for row in app:
            if not first_change <= row["probe_start_s"] < clear_time:
                continue
            healthy = row["app_loss_pct"] == 0 and row["app_rtt_ms"] is not None and row["app_rtt_ms"] < 40
            streak = streak + 1 if healthy else 0
            if streak >= 2:
                recovery = row["elapsed_s"] - fault_time
                break
    latency = [r["app_rtt_ms"] for r in app if r["app_rtt_ms"] is not None]
    return {**traffic, "route_changes": len(changes),
            "failover_changes": len(changes) - len(failbacks),
            "automatic_failbacks": len(failbacks),
            "failback_observed": bool(failbacks),
            "fault_clear_to_failback_s": after_clear[0]["elapsed_s"] - clear_time if after_clear else None,
            "fault_on_s": fault_time,
            "detection_and_actuation_s": first_change - fault_time if first_change is not None else None,
            "verified_recovery_s": recovery,
            "recovery_observed": recovery is not None,
            "unnecessary_reroutes": sum(1 for e in changes if e.get("reason") != "primary_restored" and
                                        (fault_time is None or
                                         not fault_time <= e["elapsed_s"] < clear_time or
                                         (config.scenario != "both_down" and e["source"] != config.fault_path))),
            "mean_probe_loss_pct": sum(r["app_loss_pct"] for r in app) / len(app) if app else None,
            "mean_probe_rtt_ms": sum(latency) / len(latency) if latency else None,
            "sample_windows": len(app)}
