from dataclasses import dataclass
from typing import Protocol

"""
FEATURES lists the four measurements supplied to the ML model, in the required order. 
PATHS lists our two available routes.
"""

FEATURES = ["loss_pct", "rtt_ms", "rtt_std_ms", "utilization"]      #ML Features
PATHS = ("primary", "backup")

@dataclass(frozen=True)
class Observation:
    """An Observation stores one path’s measured condition during one measurement cycle."""
    path: str                       #Which path was measured whether primary or backup.
    loss_pct: float                 #Percentage of Probe packets lost.
    rtt_ms: float | None            #Average round trip time.
    rtt_std_ms: float               #Standard deviation of RTT.
    utilization: float              #Measured traffic rate divided by configured link capacity,
    link_up: bool = True            #Whether the path’s checked links are up. True / False.

    def features(self):
        return [self.loss_pct, self.rtt_ms if self.rtt_ms is not None else 1000.0, self.rtt_std_ms, self.utilization]
        #Default value of RTT in ms is 1000.The exact number is a design choice. The important part is consistency: 
        # this project replaces missing RTT with 1000 both when training the model and when making predictions. 
        # That lets the model learn from examples containing the same marker. Goes to the FEATURES LIST.


class Detector(Protocol):
    #A detector answers one question: “Is this path unhealthy?”
    #Here, True means unhealthy and False means healthy according to that detector.
    def unhealthy(self, observation: Observation) -> bool: ...

"""
Both ThresholdDetector and MLDetector provide an unhealthy() method. 
This lets the recovery logic use either detector through the same method call.
"""

class ThresholdDetector:
    """
    It marks the path unhealthy if any one of these conditions is true:
    Measurement	                Unhealthy condition
    Packet loss	                At least 15%
    RTT availability	        No measured RTT: None
    Average RTT	                At least 40 ms
    Link utilization	        At least 90%
    """

    def unhealthy(self, observation):
        return (observation.loss_pct >= 15.0 or 
                observation.rtt_ms is None or 
                observation.rtt_ms >= 40.0 or 
                observation.utilization >= 0.90)

@dataclass(frozen = True)
class Decision:  
    """
    Its fields mean:
    Field	        Meaning
    source	        The currently selected path
    destination	    The proposed new path; None means no switch
    reason	        Why the policy reached this decision
    """
    source: str
    destination: str | None
    reason: str

class RecoveryPolicy:
    """Shared recovery policy: immediate hard-fault handling, hysteresis for soft faults.
    Both paths are probed even when inactive. A known-down path is never selected.
    A decision is committed only AFTER the actuator reports successful installation.
    Optional failback requires sustained healthy primary probes before reverting.
    """
    def __init__(self, detector, confirmations=2, hold_down=5.0, *,
                 failback=True, failback_delay=5.0, failback_confirmations=3):
        self.detector = detector                    #The supplied detector object. Judges path health.
        self.confirmations = confirmations          #Required consecutive unhealthy observations for degradation.
        self.hold_down = hold_down                  #Minimum seconds between degradation-based switches.
        self.current = "primary"                    #Tracks the selected path.
        self.streak = 0                             #Counts consecutive unhealthy observations.
        self.last_switch = float("-inf")            #Records when the last successful switch occurred.
        self.failback = failback
        self.failback_delay = failback_delay
        self.failback_confirmations = failback_confirmations
        self.primary_healthy_since = None
        self.primary_healthy_streak = 0

        "Why negative infinity? Before the first switch, there is no previous switch time. "
        "This value ensures the hold-down check permits that first switch."


    def decide(self, observations, now):
        """
        Parameter	        Meaning
        self	            This RecoveryPolicy object, containing current, streak, and the other attributes
        observations        A dictionary containing measurements for both paths
        now	                The current elapsed experiment time in seconds
        """
        active = observations[self.current]        #Therefore, this instruction selects the "primary" entry from the observations dictionary. 
        other = "backup" if self.current == "primary" else "primary"        #Assign backup if current is primary else assign primary.
        candidate = observations[other]                                     #This retrieves that path’s Observation object from the dictionary.
        failed = not active.link_up                                         #Identifies a failed hardware link.
        unhealthy = failed or self.detector.unhealthy(active)               #The active path is considered unhealthy if either: It has a hard link failure or the detector judges its measurements unhealthy.
        self.streak = self.streak + 1 if unhealthy else 0                   #Counts consecutive unhealthy observations.

        primary = observations["primary"]
        # Returning to the preferred route requires loss-free probes as well as
        # the detector's approval. A single bad window restarts the entire wait.
        primary_ready = (self.failback and self.current == "backup" and primary.link_up
                         and primary.loss_pct == 0 and primary.rtt_ms is not None
                         and primary.rtt_ms < 40 and primary.utilization < 0.90
                         and not self.detector.unhealthy(primary))
        if primary_ready:
            if self.primary_healthy_since is None:
                self.primary_healthy_since = now
            self.primary_healthy_streak += 1
        else:
            self.primary_healthy_since = None
            self.primary_healthy_streak = 0

        #Checks for healthy / unhealthy.

        if not unhealthy:
            if primary_ready:
                if (self.primary_healthy_streak < self.failback_confirmations
                        or now - self.primary_healthy_since < self.failback_delay):
                    return Decision(self.current, None, "awaiting_primary_stability")
                if now - self.last_switch < self.hold_down:
                    return Decision(self.current, None, "hold_down")
                return Decision(self.current, "primary", "primary_restored")
            return Decision(self.current, None, "healthy")                  #If primary is healthy, there is no reason to change routes.
                            #<source>, <dest.>, <reason>

        if not candidate.link_up or self.detector.unhealthy(candidate):      
            return Decision(self.current, None, "no_healthy_alternative")       #We reach this only when the current path is unhealthy. It checks whether backup is down or has unhealthy measurements. If either is true, there is no healthy alternative to select.
        
        if not failed and self.streak < self.confirmations:                     #One bad reading might be temporary. Wait until we get enough bad readings in a row before switching.” Default: 2 consecutive bad readings.
            return Decision(self.current, None, "awaiting_confirmation")        

        if not failed and now - self.last_switch < self.hold_down:              #We switched routes recently. Wait before switching again.
            return Decision(self.current, None, "hold_down")

        return Decision(self.current, other, "link_down" if failed else "degradation")  #The current path has a problem, the alternative is healthy, and any required waiting is over. Propose switching to the alternative.

    def commit(self, decision, now):
        """
        The route switch succeeded. Update our records to match it.
        """
        if decision.source != self.current or decision.destination not in PATHS:
            raise ValueError("Cannot commit stale or empty decision")       
        
        self.current = decision.destination
        self.last_switch = now
        self.streak = 0
        self.primary_healthy_since = None
        self.primary_healthy_streak = 0
