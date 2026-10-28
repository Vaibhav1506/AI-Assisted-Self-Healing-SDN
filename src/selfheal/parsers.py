"""Strict parsers: missing measurements are never silently called healthy."""
import json
import re


def parse_ping(output):
    loss = re.search(r"([\d.]+)% packet loss", output)
    if not loss:
        raise ValueError(f"No packet-loss summary in ping output: {output[:200]}")
    rtt = re.search(r"(?:rtt|round-trip)[^=]*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", output)
    pct = float(loss.group(1))
    if pct < 100 and rtt is None:
        raise ValueError("Ping received packets but has no RTT summary")
    return {"loss_pct": pct, "rtt_ms": float(rtt.group(2)) if rtt else None,
            "rtt_std_ms": float(rtt.group(4)) if rtt else 0.0}


def parse_tx_bytes(output):
    match = re.search(r"tx pkts=\d+, bytes=(\d+)", output)
    if not match:
        raise ValueError(f"No TX byte counter: {output[:200]}")
    return int(match.group(1))


def parse_iperf(path):
    with open(path) as handle:
        result = json.load(handle)
    if "error" in result:
        raise ValueError(f"iperf3: {result['error']}")
    end = result.get("end", {})
    # Prefer receiver-side server output; sender throughput is offered load.
    server = result.get("server_output_json", {})
    receiver = server.get("end", {}).get("sum_received") or server.get("end", {}).get("sum")
    receiver = receiver or end.get("sum_received")
    if receiver is None:
        raise ValueError("iperf3 output has no receiver summary")
    return {"receiver_mbps": receiver["bits_per_second"] / 1e6,
            "udp_loss_pct": receiver.get("lost_percent"),
            "udp_jitter_ms": receiver.get("jitter_ms"),
            "received_bytes": receiver.get("bytes")}
