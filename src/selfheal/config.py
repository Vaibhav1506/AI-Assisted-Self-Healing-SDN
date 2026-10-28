from dataclasses import asdict, dataclass
import math

"""
Scenario	    Meaning
normal	        Run without an injected fault
link_down	    Bring down a link on the selected path
loss	        Introduce packet loss
delay	        Increase link delay
congestion	    Generate additional traffic to congest a path
both_down	    Bring down links on both available paths

Recovery Approach:
static	        Keep the initial route without automatic recovery
threshold	    Detect degradation using fixed rules
ml	            Use a trained model to detect degradation
"""

SCENARIOS = ("normal", "link_down", "loss", "delay", "congestion", "both_down")
MODES = ("static", "threshold", "ml")


"""
All time fields above use seconds, except delay_ms, 
which uses milliseconds. Traffic rates use Mbps.
"""

@dataclass(frozen = True)
class ExperimentConfig:
    mode: str = "threshold"         #Recovery approach
    scenario: str = "link_down"     #Network condition to introduce
    duration: float = 36.0          #Requested experiment duration, in seconds
    fault_start: float = 10.0       #Fault start time.
    fault_end: float = 26.0         #Fault end time.
    interval: float = 1.0           #Requested time between measurement cycles.
    load_mbps: float = 4.0          #Application traffic rate.
    capacity_mbps: float = 10.0     #Configured capacity of each interval network link.
    loss_pct: float = 20.0          #Configured packet loss for the loss scenario.
    delay_ms: float = 60.0          #Configured impaired-link delay for the delay scenario.
    background_mbps: float = 12.0   #Additional traffic rate for the congestion scenario.
    seed: int = 1                   #Identifier for an experiment group.
    fault_path: str = "primary"     #Path on which to introduce the fault.
    confirmations: int = 2          #Consecutive unhealthy observations required for degradation-based switching.
    hold_down: float = 5.0          #Minimum time between degradation-based switches.
    failback: bool = True           #Return to primary after sustained healthy probes.
    failback_delay: float = 5.0     #Minimum continuously healthy time before failback.
    failback_confirmations: int = 3 #Consecutive healthy observations required for failback.

    def validate(self): #Validation scenarios.  
        if self.mode not in MODES or self.scenario not in SCENARIOS:
            raise ValueError("Unknown mode or scenario")           
        
        if self.fault_path not in ("primary", "backup"):
            raise ValueError("fault_path must be primary or backup")
        
        for key, value in asdict(self).items():
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ValueError(f"{key} must be finite")
        
        if not 0 < self.fault_start < self.fault_end < self.duration:
            raise ValueError("Require 0 < fault_start < fault_end < duration")
        
        if self.interval < 0.5 or self.duration < 6:
            raise ValueError("interval must be >= 0.5 seconds and duration >= 6")
        
        if not 0 < self.load_mbps <= 100 or not 0 < self.capacity_mbps <= 100:
            raise ValueError("Traffic load and capacity must be in (0, 100] Mbps")
        
        if not 0 <= self.loss_pct <= 100 or not 0 < self.delay_ms <= 1000:
            raise ValueError("Invalid loss percentage or delay")
        
        if not 0 < self.background_mbps <= 200:
            raise ValueError("Background rate must be in (0, 200] Mbps")
        
        if self.confirmations < 1 or self.hold_down < 0:
            raise ValueError("Invalid confirmation count or hold-down")
        if not isinstance(self.failback, bool):
            raise ValueError("failback must be a boolean")
        if isinstance(self.failback_delay, bool) or self.failback_delay < 0:
            raise ValueError("failback_delay must be non-negative")
        if (type(self.failback_confirmations) is not int
                or self.failback_confirmations < 1):
            raise ValueError("failback_confirmations must be a positive integer")
        
        return self
