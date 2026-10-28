"""Four- and six-switch topology support shared by the Python demonstration."""
from contextlib import contextmanager
from dataclasses import dataclass

from . import experiment, network, telemetry
from .config import ExperimentConfig

TOPOLOGIES = ("diamond", "long_diamond")
METHODS = ("rf_without_loss_guard", "rf_without_loss", "threshold")


@dataclass(frozen=True)
class DemoConfig(ExperimentConfig):
    topology: str = "diamond"
    method: str = "threshold"

    def validate(self):
        super().validate()
        if self.topology not in TOPOLOGIES or self.method not in METHODS:
            raise ValueError("Unknown topology or detector")
        if self.mode != ("threshold" if self.method == "threshold" else "ml"):
            raise ValueError("Detector and runtime mode disagree")
        return self


class ExtendedLaboratory(network.Laboratory):
    """Reuse the lab, inserting an extra switch on each six-switch branch."""
    def add_link(self, a, b, **options):
        middle = {("cnS2", "cnS3"): "cnS5", ("cnS4", "cnS3"): "cnS6"}.get((a, b))
        if self.config.topology == "long_diamond" and middle:
            super().add_link(a, middle, **options)
            super().add_link(middle, b, **options)
        else:
            super().add_link(a, b, **options)

    def install_pair(self, nodes, src, dst, priority=100):
        expanded = [nodes[0]]
        for a, b in zip(nodes, nodes[1:]):
            if self.config.topology == "long_diamond":
                middle = {frozenset(("cnS2", "cnS3")): "cnS5",
                          frozenset(("cnS4", "cnS3")): "cnS6"}.get(frozenset((a, b)))
                if middle:
                    expanded.append(middle)
            expanded.append(b)
        super().install_pair(tuple(expanded), src, dst, priority)


@contextmanager
def topology_context(topology):
    """Select routes for one locked run and restore bindings on every exit.

    This context is process-local. Live callers must hold the project lock and
    must not run two topologies concurrently in the same Python process.
    """
    if topology not in TOPOLOGIES:
        raise ValueError("Unknown topology")
    original = (network.SWITCHES, network.ROUTES, telemetry.ROUTES, experiment.Laboratory)
    try:
        if topology == "long_diamond":
            network.SWITCHES = (*original[0], "cnS5", "cnS6")
            network.ROUTES = {"primary": ("cnS1", "cnS2", "cnS5", "cnS3"),
                              "backup": ("cnS1", "cnS4", "cnS6", "cnS3")}
            telemetry.ROUTES = network.ROUTES
        experiment.Laboratory = ExtendedLaboratory
        yield
    finally:
        network.SWITCHES, network.ROUTES, telemetry.ROUTES, experiment.Laboratory = original
