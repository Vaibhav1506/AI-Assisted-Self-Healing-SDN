"""Python-only demonstration commands; imports and help never start a network."""
import argparse
from contextlib import contextmanager
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime"


@contextmanager
def network_lock():
    RUNTIME.mkdir(exist_ok=True)
    with (RUNTIME / "network.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another project demo is running") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def doctor():
    from .learning import verify_model
    binaries = {name: shutil.which(name) for name in
                ("ovs-vsctl", "ovs-ofctl", "iperf3", "ping", "tc", "ip", "ss", "mnexec")}
    modules = {name: importlib.util.find_spec(name) is not None
               for name in ("mininet", "numpy", "sklearn", "joblib")}
    try:
        verify_model()
        model = "ready"
    except (OSError, ValueError) as error:
        model = str(error)
    print(json.dumps({"binaries": binaries, "modules": modules, "trained_detector": model,
                      "live_network_verified": False,
                      "note": "Availability check only. Use smoke to verify the live network."}, indent=2))
    return 0 if all(binaries.values()) and all(modules.values()) and model == "ready" else 1


def show_result(directory=None):
    if directory is None:
        attempts = list((RUNTIME / "runs").glob("*/metadata.json"))
        if not attempts:
            print("No demo has run yet. Run sudo python3 main.py and wait for COMPLETE.")
            return 1
        directory = max(attempts, key=lambda path: path.parent.name).parent
    directory = Path(directory)
    metadata = json.loads((directory / "metadata.json").read_text())
    config = metadata["config"]
    print(f"\nStatus: {metadata['status']}")
    print(f"Detector: {config['method']} | Topology: {config['topology']} | Scenario: {config['scenario']}")
    if metadata["status"] != "complete":
        print(f"Run did not complete: {metadata.get('error', 'Still running')}")
        return 1
    summary = json.loads((directory / "summary.json").read_text())
    from . import display
    display.configuration(config)
    print("\nEVENT TIMELINE — elapsed seconds from traffic start")
    event_file = directory / "events.jsonl"
    if event_file.exists():
        for line in event_file.read_text().splitlines():
            if line.strip():
                display.event_line(json.loads(line))
    display.results(summary, config)
    samples_file = directory / "samples.csv"
    if samples_file.exists():
        import csv
        from collections import Counter
        with samples_file.open(newline="") as handle:
            samples = [row for row in csv.DictReader(handle) if row["path"] == "primary"]
        counts = Counter(row["decision"] for row in samples if row["fault_active"] == "True")
        if counts:
            print("\nCONTROLLER DECISIONS DURING FAULT (one per measurement cycle)")
            for reason, count in counts.items():
                print(f"  {reason}: {count}")
            print("  'healthy' is the detector's assessment, not proof the path was fault-free.")
    print(f"\nEVIDENCE DIRECTORY: {directory}")
    print("  events.jsonl           : actual fault and route-change times")
    print("  samples.csv            : both paths' probes, utilization and controller decisions")
    print("  summary.json           : aggregate metrics; metadata.json: full configuration")
    print("  application-iperf.json : raw UDP traffic results; *-flows.txt: final forwarding rules")
    return 0


def parser():
    from .config import SCENARIOS
    from .topology import METHODS, TOPOLOGIES
    p = argparse.ArgumentParser(description="Self-healing SDN demo. With no arguments: guarded ML on six switches.")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("demo", "run"):
        demo = commands.add_parser(name, help="Run one 36-second demonstration")
        demo.add_argument("--method", choices=METHODS, default="rf_without_loss_guard")
        demo.add_argument("--topology", choices=TOPOLOGIES, default="long_diamond")
        demo.add_argument("--scenario", choices=SCENARIOS, default="loss")
        demo.add_argument("--load", type=float, default=4)
        demo.add_argument("--capacity", type=float, default=10, help="Inter-switch link capacity in Mbps (0 < capacity <= 100); congestion background is 1.2 times capacity")
        demo.add_argument("--failback", action=argparse.BooleanOptionalAction, default=True,
                          help="Automatically return to primary after sustained healthy probes (default: enabled)")
        demo.add_argument("--failback-delay", type=float, default=5,
                          help="Minimum continuously healthy primary time before returning, in seconds (default: 5)")
        demo.add_argument("--failback-confirmations", type=int, default=3,
                          help="Consecutive healthy primary observations before returning (default: 3)")
    commands.add_parser("doctor", help="Check dependencies and the trained detector")
    commands.add_parser("smoke", help="Short live failover and failback check on six switches")
    commands.add_parser("show", help="Show the latest demo attempt without starting a network")
    return p


def run_demo(args):
    from . import experiment, network
    from .learning import MODEL, verify_model
    from .topology import DemoConfig, topology_context
    if os.geteuid() != 0:
        raise PermissionError("Live networking needs administrator access. Run: sudo python3 main.py")
    if args.command == "smoke":
        config = DemoConfig(topology="long_diamond", duration=22, fault_start=3, fault_end=11, confirmations=1)
    else:
        config = DemoConfig(topology=args.topology, method=args.method, scenario=args.scenario,
                            mode="threshold" if args.method == "threshold" else "ml", load_mbps=args.load,
                            capacity_mbps=args.capacity, background_mbps=1.2 * args.capacity, seed=20001,
                            failback=args.failback, failback_delay=args.failback_delay,
                            failback_confirmations=args.failback_confirmations)
    config.validate()
    model = verify_model(MODEL) if config.mode == "ml" else None
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        with network_lock():
            # Check every reserved switch even when a four-switch demo is chosen.
            with topology_context("long_diamond"):
                network.preflight()
            print(f"DEMO: {config.method}, {config.topology}, {config.scenario}. "
                  f"{config.duration:g} seconds of traffic plus setup/cleanup. Wait for COMPLETE.", flush=True)
            with topology_context(config.topology):
                directory = experiment.run_experiment(config, RUNTIME / "runs", model=model,
                                                      purpose="smoke" if args.command == "smoke" else "evaluation")
            if args.command == "smoke":
                summary = json.loads((directory / "summary.json").read_text())
                if (summary["route_changes"] != 2 or summary["failover_changes"] != 1
                        or summary["automatic_failbacks"] != 1 or not summary["recovery_observed"]
                        or summary["fault_clear_to_failback_s"] is None):
                    raise RuntimeError(f"Smoke failed: inspect {directory}")
                print("SMOKE PASSED: injected link failure, verified failover recovery, returned to primary.")
            return show_result(directory)
    finally:
        signal.signal(signal.SIGTERM, previous)


def main(argv=None):
    args = parser().parse_args((sys.argv[1:] if argv is None else argv) or ["demo"])
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == "show":
            return show_result()
        return run_demo(args)
    except KeyboardInterrupt:
        print("Interrupted; network cleanup requested. Run again for a new demonstration.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
