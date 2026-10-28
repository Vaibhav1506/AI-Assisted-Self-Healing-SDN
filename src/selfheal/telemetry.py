"""Concurrent active path probes and measured switch byte-counter deltas."""
import os
import subprocess
import time
from .core import Observation
from .network import HOST_IPS, PROBES, ROUTES
from .parsers import parse_ping, parse_tx_bytes


class Monitor:
    def __init__(self, lab):
        self.lab = lab
        self.previous = {}

    def measure(self):
        probes = {}
        env = {**os.environ, "LC_ALL": "C"}
        try:
            for name, address in {**PROBES, "application": HOST_IPS["h2"]}.items():
                probes[name] = self.lab.net.get("h1").popen(
                    ["ping", "-n", "-q", "-c", "5", "-i", "0.05", "-W", "0.3", "-w", "2", address],
                    text=True, env=env)
            measured = {}
            for name, process in probes.items():
                out, err = process.communicate(timeout=4)
                if process.returncode not in (0, 1):
                    raise RuntimeError(f"Probe failed ({name}): {err or out}")
                measured[name] = parse_ping(out)
        finally:
            for process in probes.values():
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        states = self.lab.interface_state()
        observations = {}
        now = time.monotonic()
        for path, route in ROUTES.items():
            totals = []
            for a, b in (route[-2:], tuple(reversed(route[-2:]))):
                port = self.lab.ports[a, b][0]
                counter = parse_tx_bytes(self.lab.ofctl("dump-ports", a, port))
                key = (a, b)
                old = self.previous.get(key)
                utilization = (max(0, counter - old[1]) * 8 / (now - old[0]) /
                               (self.lab.config.capacity_mbps * 1e6)) if old else 0.0
                self.previous[key] = (now, counter)
                totals.append(utilization)
            observations[path] = Observation(path, **measured[path], utilization=max(totals),
                                             link_up=states[path])
        return observations, measured["application"]
