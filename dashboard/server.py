"""Local SDN dashboard. Standard library only; networking stays in main.py."""
import argparse
import csv
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
RUNS = PROJECT / ".runtime" / "runs"
METHODS = ("rf_without_loss_guard", "rf_without_loss", "threshold")
TOPOLOGIES = ("long_diamond", "diamond")
SCENARIOS = ("normal", "link_down", "loss", "congestion", "delay", "both_down")
EVIDENCE = {"metadata.json", "summary.json", "events.jsonl", "samples.csv", "application-iperf.json"}
RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def run_directory(run_id):
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid experiment ID")
    directory = RUNS / run_id
    if directory.is_symlink() or not directory.is_dir():
        raise FileNotFoundError("Experiment not found")
    return directory


def record(directory, detail=False):
    metadata = read_json(directory / "metadata.json")
    if not metadata:
        return None
    result = {"id": directory.name, "status": metadata.get("status"),
              "config": metadata.get("config", {}), "started": metadata.get("started_utc"),
              "error": metadata.get("error"), "summary": read_json(directory / "summary.json"),
              "purpose": metadata.get("purpose", "evaluation")}
    if not detail:
        return result
    events = []
    try:
        for line in (directory / "events.jsonl").read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass  # A writer may still be appending its last line.
    except OSError:
        pass
    samples = []
    try:
        content = (directory / "samples.csv").read_text()
        # Ignore an incomplete final row while the runner is writing.
        content = content[:content.rfind("\n") + 1]
        for row in csv.DictReader(io.StringIO(content)):
            clean = {}
            for key, value in row.items():
                if key is None:
                    continue
                if value in (None, "", "None"):
                    clean[key] = None
                elif value in ("True", "False"):
                    clean[key] = value == "True"
                else:
                    try:
                        number = float(value)
                        clean[key] = number if math.isfinite(number) else None
                    except ValueError:
                        clean[key] = value
            if clean.get("elapsed_s") is not None and clean.get("path") in ("primary", "backup"):
                samples.append(clean)
    except OSError:
        pass
    result.update(events=events, samples=samples,
                  evidence=[name for name in sorted(EVIDENCE) if (directory / name).is_file()])
    return result


def history():
    if not RUNS.is_dir():
        return []
    return [value for path in sorted(RUNS.iterdir(), reverse=True)
            if RUN_ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink()
            and (value := record(path))]


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError("Expected an experiment configuration")
    for key, choices in (("scenario", SCENARIOS), ("topology", TOPOLOGIES), ("method", METHODS)):
        if data.get(key) not in choices:
            raise ValueError(f"Choose a supported {key}")
    load = data.get("load", 4)
    if isinstance(load, bool) or not isinstance(load, (int, float)) or not 0 < load <= 100 or not math.isfinite(load):
        raise ValueError("Traffic load must be greater than 0 and at most 100 Mbps")
    capacity = data.get("capacity", 10)
    if isinstance(capacity, bool) or not isinstance(capacity, (int, float)) or not math.isfinite(capacity) or not 0 < capacity <= 100:
        raise ValueError("Link capacity must be greater than 0 and at most 100 Mbps")
    failback = data.get("failback", True)
    if not isinstance(failback, bool):
        raise ValueError("Automatic return to primary must be enabled or disabled")
    failback_delay = data.get("failback_delay", 5)
    if (isinstance(failback_delay, bool) or not isinstance(failback_delay, (int, float))
            or not math.isfinite(failback_delay) or failback_delay < 0):
        raise ValueError("Primary stability wait must be a finite, non-negative number of seconds")
    failback_confirmations = data.get("failback_confirmations", 3)
    if type(failback_confirmations) is not int or failback_confirmations < 1:
        raise ValueError("Healthy primary observations must be a positive integer")
    return {key: data[key] for key in ("scenario", "topology", "method")} | {
        "load": load, "capacity": capacity, "failback": failback,
        "failback_delay": failback_delay, "failback_confirmations": failback_confirmations}


class Runner:
    def __init__(self, live=False):
        self.live = live
        self.lock = threading.RLock()
        self.process = None
        self.state = {"busy": False, "phase": "idle", "run_id": None, "queue": [],
                      "completed_ids": [], "error": None, "output": [], "config": None}
        self.cancelled = False

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def start(self, config, compare=False):
        if not self.live:
            raise PermissionError("Live experiments need administrator access. Restart with: sudo python3 dashboard/server.py")
        config = validate_config(config)
        configs = [config | {"method": method} for method in METHODS] if compare else [config]
        with self.lock:
            if self.state["busy"]:
                raise RuntimeError("An experiment is already running. Wait for it to finish or stop it first.")
            self.cancelled = False
            self.state = {"busy": True, "phase": "starting", "run_id": None, "queue": configs,
                          "completed_ids": [], "error": None, "output": [], "config": config}
            threading.Thread(target=self._work, args=(configs,), daemon=True).start()

    def _work(self, configs):
        try:
            for index, config in enumerate(configs):
                with self.lock:
                    if self.cancelled:
                        break
                    self.state.update(phase="starting", run_id=None, config=config, queue=configs[index + 1:])
                    args = [sys.executable, "-u", str(PROJECT / "main.py"), "demo",
                            "--scenario", config["scenario"], "--topology", config["topology"],
                            "--method", config["method"], "--load", str(config["load"]),
                            "--capacity", str(config["capacity"]),
                            "--failback" if config["failback"] else "--no-failback",
                            "--failback-delay", str(config["failback_delay"]),
                            "--failback-confirmations", str(config["failback_confirmations"])]
                    self.process = subprocess.Popen(args, cwd=PROJECT, stdout=subprocess.PIPE,
                                                    stderr=subprocess.STDOUT, text=True,
                                                    env={**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "dumb"})
                    process = self.process
                for line in process.stdout:
                    line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
                    with self.lock:
                        if line:
                            self.state["output"] = (self.state["output"] + [line])[-80:]
                        match = re.match(r"RUN (\d{8}T\d{6}Z-[0-9a-f]{8}):", line)
                        if match:
                            self.state.update(run_id=match[1], phase="running")
                code = process.wait()
                process.stdout.close()
                with self.lock:
                    self.process = None
                    run_id = self.state["run_id"]
                    if run_id:
                        self.state["completed_ids"].append(run_id)
                    if code and not self.cancelled:
                        self.state["error"] = next((line for line in reversed(self.state["output"])
                                                    if line.strip()), "The experiment did not complete.")
                        break
        except Exception as error:
            with self.lock:
                self.state["error"] = str(error)
        finally:
            with self.lock:
                self.state.update(busy=False, queue=[], phase="stopped" if self.cancelled else
                                  "failed" if self.state["error"] else "complete")

    def stop(self):
        with self.lock:
            self.cancelled = True
            self.state["queue"] = []
            if self.process and self.process.poll() is None:
                self.state["phase"] = "stopping"
                self.process.send_signal(signal.SIGTERM)


class Dashboard(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, live=False):
        self.token = secrets.token_urlsafe(32)
        self.runner = Runner(live)
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "SDN-Dashboard"

    def log_message(self, *_args):
        pass

    def send(self, code, value, mime="application/json", filename=None):
        body = json.dumps(value, allow_nan=False).encode() if mime == "application/json" else value
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def trusted_host(self):
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def do_GET(self):
        if not self.trusted_host():
            return self.send(403, {"error": "Use the local dashboard address"})
        path = urlsplit(self.path).path
        try:
            if path == "/api/session":
                return self.send(200, {"token": self.server.token, "live_enabled": self.server.runner.live})
            if path == "/api/runs":
                return self.send(200, history())
            if path == "/api/state":
                return self.send(200, self.server.runner.snapshot())
            if path.startswith("/api/runs/"):
                parts = path.split("/")
                directory = run_directory(parts[3])
                if len(parts) == 4:
                    result = record(directory, detail=True)
                    if result is None:
                        raise FileNotFoundError("Experiment is not ready yet")
                    return self.send(200, result)
                if len(parts) == 6 and parts[4] == "files" and parts[5] in EVIDENCE:
                    file = directory / parts[5]
                    if file.is_symlink():
                        raise ValueError("Invalid evidence file")
                    return self.send(200, file.read_bytes(), "application/octet-stream", f"{directory.name}-{file.name}")
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/styles.css": ("styles.css", "text/css; charset=utf-8")}
            if path in assets:
                name, mime = assets[path]
                return self.send(200, (HERE / "static" / name).read_bytes(), mime)
            return self.send(404, {"error": "Not found"})
        except (ValueError, FileNotFoundError, OSError) as error:
            return self.send(404, {"error": str(error)})

    def do_POST(self):
        origins = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        token = self.headers.get("X-Dashboard-Token", "")
        if not self.trusted_host() or self.headers.get("Origin") not in origins or not hmac.compare_digest(token, self.server.token):
            return self.send(403, {"error": "Reload the local dashboard before running an experiment"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 4096:
                raise ValueError("Request is too large")
            data = json.loads(self.rfile.read(length) or b"{}")
            path = urlsplit(self.path).path
            if path in ("/api/run", "/api/compare"):
                self.server.runner.start(data, compare=path == "/api/compare")
            elif path == "/api/stop":
                self.server.runner.stop()
            else:
                return self.send(404, {"error": "Not found"})
            return self.send(202, self.server.runner.snapshot())
        except PermissionError as error:
            return self.send(403, {"error": str(error)})
        except (ValueError, TypeError) as error:
            return self.send(400, {"error": str(error)})
        except RuntimeError as error:
            return self.send(409, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = Dashboard(args.port, live=os.geteuid() == 0)
    print(f"SDN dashboard: http://127.0.0.1:{server.server_port}", flush=True)
    print("Live experiments enabled." if server.runner.live else
          "Saved runs ready. For live controls: sudo python3 dashboard/server.py", flush=True)
    def terminate(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.runner.stop()
        process = server.runner.process
        if process:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                print("Experiment cleanup is still running; waiting for the runner.", flush=True)
                process.wait()
        server.server_close()


if __name__ == "__main__":
    main()
