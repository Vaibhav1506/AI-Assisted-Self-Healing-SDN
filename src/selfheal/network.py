"""
Mininet topology and explicit OpenFlow forwarding for a loop-free diamond.
This is a local centralized controller using ovs-ofctl as its OpenFlow client.
It is NOT a persistent remote OpenFlow controller or a production SDN platform.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess


SWITCHES = ("cnS1", "cnS2", "cnS3", "cnS4")
#Switches S1 to S4.

ROUTES = {"primary": ("cnS1", "cnS2", "cnS3"),
          "backup": ("cnS1", "cnS4", "cnS3")}
#2 routes one primary and other backup

PROBES = {"primary": "10.77.0.102", 
          "backup": "10.77.0.103"}
#A probe is test traffic used to measure a path’s condition—for example, ping packets used to measure loss and RTT. 102 is the primary and 103 the backup.

HOST_IPS = {"h1": "10.77.0.1", "h2": "10.77.0.2",
            "b1": "10.77.0.3", "b2": "10.77.0.4",
            "b3": "10.77.0.5", "b4": "10.77.0.6"}
#Host IPs. h is for host and b for background. 
"""
h1 → h2   Main application traffic
b1 → b2   Background traffic on the primary path (background traffic is for creating congestions.)
b3 → b4   Background traffic on the backup path
"""

def command(args, **kwargs):
    "Run a system command, wait for it to finish, and return its output as text."
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=10, **kwargs).stdout

def preflight():
    """
    Checking that everything is ready before starting.
    """
    if os.geteuid() != 0:
        "Not running as root."
        raise PermissionError("Live networking needs root. Run: sudo python3 main.py")

    for program in ("ovs-vsctl", "ovs-ofctl", "ip", "tc", "ping", "iperf3", "mnexec", "ss"):
        if not shutil.which(program):
            raise RuntimeError(f"Missing system program: {program}")

    #Collision Checking
    existing = command(["ovs-vsctl", "--timeout=5", "list-br"]).split() #Returns existing switches.
    collisions = set(existing).intersection(SWITCHES)       #Finds switches already running.


    if collisions:
        raise RuntimeError(f"Project bridges already exist: {sorted(collisions)}. "
                           "Check for a running project before removing stale bridges.")


class Laboratory:
    def __init__(self, config):
        self.config = config        #Supplied ExperimentConfig object.
        self.net = None             #Mininet Networking object.
        self.ports = {}             #Port numbers and interface names for connections.
        self.links = {}             #Link objects.
        self.processes = []         #Processes started by this class.
        self.handles = []           #Open output file objects used to record process output.

    def __enter__(self):
        preflight() #Make sure everything is good.
        from mininet.net import Mininet
        from mininet.node import OVSSwitch
        from mininet.link import TCLink
        from mininet.log import setLogLevel

        setLogLevel("warning")
        self.net = Mininet(controller=None, switch=OVSSwitch, link=TCLink, build=False, autoSetMacs=False)  #Create a mininet using OVSSwitch and TCLink.
        
        try:
            for name in SWITCHES: #Add switches with OpenFlow13 protocol which is a forwarding rule. With failMode="secure", we retain explicit control over forwarding through the installed rules.
                self.net.addSwitch(name, protocols="OpenFlow13", failMode="secure")


            for i, (name, address) in enumerate(HOST_IPS.items(), 1): #This adds our six hosts, giving each an IP address and a unique MAC address.
                self.net.addHost(name, ip=address + "/24", mac=f"02:00:00:00:00:{i:02x}")

        
            for host, switch in (("h1", "cnS1"), ("h2", "cnS3"),
                                 ("b1", "cnS2"), ("b2", "cnS3"),    #Connects each switch and to its host using links.
                                 ("b3", "cnS4"), ("b4", "cnS3")):
                self.add_link(host, switch)
        
            for a, b, delay in (("cnS1", "cnS2", "2ms"), ("cnS2", "cnS3", "2ms"),
                                ("cnS1", "cnS4", "3ms"), ("cnS4", "cnS3", "3ms")):
                self.add_link(a, b, bw=self.config.capacity_mbps, delay=delay,  #Connected switches between the switches using a delay.
                              max_queue_size=100)
                
            self.net.build()    #Build and start.
            self.net.start()
            
            for address in PROBES.values():     #This adds both probe IP addresses to h2.
                self.host_command("h2", ["ip", "addr", "add", address + "/24", "dev", "h2-eth0"])

            #This creates one dictionary containing all host IP addresses and both probe IP addresses.
            addresses = {**HOST_IPS, **{p: ip for p, ip in PROBES.items()}}

            """
            The resulting dictionary looks like:
            addresses = {
                "h1": "10.77.0.1",
                "h2": "10.77.0.2",
                "b1": "10.77.0.3",
                "b2": "10.77.0.4",
                "b3": "10.77.0.5",
                "b4": "10.77.0.6",
                "primary": "10.77.0.102",
                "backup": "10.77.0.103",
            }
            There are eight address entries for six hosts. The "primary" and "backup" entries label the extra addresses belonging to h2.
            """

            #This nested loop gives each virtual host an IP-to-MAC “address book.” 
            # It tells each host which MAC address corresponds to each destination IP.
            for host in HOST_IPS:
                for peer, address in addresses.items():
                    mac = self.net.get(peer if peer in HOST_IPS else "h2").MAC()
                    if address != HOST_IPS[host]:
                        self.host_command(host, ["ip", "neigh", "replace", address, "lladdr", mac, "nud", "permanent", "dev", host + "-eth0"])
            
            self.install_initial()  #Configure the switches so packets follow our intended paths.
            return self
        
        except BaseException:
            self.close()    
            raise

    def add_link(self, a, b, **options):
        link = self.net.addLink(a, b, **options)    #calls Mininet’s addLink() method. It creates the connection, returns a link object, and we store that object in link.
        self.links[frozenset((a, b))] = link        #saves that object in our self.links dictionary.

        for first, second, intf in ((a, b, link.intf1), (b, a, link.intf2)):
            self.ports[first, second] = (intf.node.ports[intf], intf.name)  #

    def host_command(self, host, args):
        process = self.net.get(host).popen(args, text=True)
        try:
            out, err = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            raise RuntimeError(f"{host}: {args}: {err or out}")
        return out

    def ofctl(self, *args):
        return command(["ovs-ofctl", "--no-names", "-O", "OpenFlow13", *map(str, args)])

    def install_pair(self, nodes, src, dst, priority=100):
        for direction, source, destination in ((nodes, src, dst), (tuple(reversed(nodes)), dst, src)):
            for i, node in enumerate(direction[1:-1], 1):
                port = self.ports[node, direction[i + 1]][0]
                self.ofctl("add-flow", node,
                           f"priority={priority},ip,nw_src={source},nw_dst={destination},actions=output:{port}")

    def install_initial(self):
        for switch in SWITCHES:
            self.ofctl("add-flow", switch, "priority=0,actions=drop")
        # Install all interior data rules before choosing the ingress path.
        for path, switches in ROUTES.items():
            self.install_pair(("h1", *switches, "h2"), HOST_IPS["h1"], HOST_IPS["h2"])
            self.install_pair(("h1", *switches, "h2"), HOST_IPS["h1"], PROBES[path], 200)
        self.install_pair(("b1", "cnS2", "cnS3", "b2"), HOST_IPS["b1"], HOST_IPS["b2"])
        self.install_pair(("b3", "cnS4", "cnS3", "b4"), HOST_IPS["b3"], HOST_IPS["b4"])
        self.activate("primary")

    def activate(self, path):
        switches = ROUTES[path]
        # Interior rules are already present. These two ingress changes are sequential,
        # not a cross-switch atomic transaction; bidirectional routes can differ briefly.
        for edge, neighbor, src, dst in (("cnS3", switches[-2], HOST_IPS["h2"], HOST_IPS["h1"]),
                                         ("cnS1", switches[1], HOST_IPS["h1"], HOST_IPS["h2"])):
            port = self.ports[edge, neighbor][0]
            self.ofctl("--strict", "mod-flows", edge,
                       f"priority=100,ip,nw_src={src},nw_dst={dst},actions=output:{port}")
            installed = self.ofctl("dump-flows", edge, f"ip,nw_src={src},nw_dst={dst}")
            if f"actions=output:{port}" not in installed:
                raise RuntimeError(f"Forwarding update verification failed on {edge}")

    def interface_state(self):
        interfaces = json.loads(command(["ip", "-j", "link", "show"]))
        flags = {row["ifname"]: row["flags"] for row in interfaces}
        states = {}
        for path, route in ROUTES.items():
            names = [self.ports[a, b][1] for a, b in zip(route, route[1:])]
            names += [self.ports[b, a][1] for a, b in zip(route, route[1:])]
            states[path] = all("UP" in flags.get(name, []) and "LOWER_UP" in flags.get(name, [])
                               for name in names)
        return states

    def set_fault(self, enabled):
        cfg = self.config
        if cfg.scenario in ("normal", "congestion"):
            return
        paths = ROUTES if cfg.scenario == "both_down" else [cfg.fault_path]
        for path in paths:
            a, b = ROUTES[path][-2:]
            if cfg.scenario in ("link_down", "both_down"):
                self.net.configLinkStatus(a, b, "down" if enabled else "up")
            else:
                link = self.links[frozenset((a, b))]
                base = 2 if path == "primary" else 3
                for intf in (link.intf1, link.intf2):
                    result = intf.config(bw=cfg.capacity_mbps,
                                        delay=f"{cfg.delay_ms if enabled and cfg.scenario == 'delay' else base}ms",
                                        loss=cfg.loss_pct if enabled and cfg.scenario == "loss" else 0,
                                        max_queue_size=100)
                    errors = [s for s in result.get("tcoutputs", []) if s.strip()]
                    if errors:
                        raise RuntimeError(f"Traffic-control configuration failed: {errors}")

    def spawn(self, host, args, stdout=None):
        process = self.net.get(host).popen(args, stdout=stdout or subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True)
        self.processes.append(process)
        return process

    def file_process(self, host, args, path):
        handle = open(path, "w")
        self.handles.append(handle)
        return self.spawn(host, args, stdout=handle)

    def close(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in self.handles:
            handle.close()
        if self.net is not None:
            self.net.stop()
            self.net = None

    def __exit__(self, *_):
        self.close()

    def snapshot(self, directory):
        for switch in SWITCHES:
            (Path(directory) / f"{switch}-flows.txt").write_text(self.ofctl("dump-flows", switch))
