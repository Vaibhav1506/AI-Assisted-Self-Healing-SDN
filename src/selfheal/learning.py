"""Load the fitted forest and optionally apply the measured-loss safeguard."""
import hashlib
from pathlib import Path

from .core import FEATURES

MODEL = Path(__file__).parent / "assets" / "detector.joblib"
MODEL_SHA256 = "5f3528e6490b50c7fc7e2a33f1556533ac5ebc00356a85f99235ae4458983001"


def verify_model(path=MODEL):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"The trained detector is missing: {path}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("The trained detector file has changed or is damaged")
    return path


class LossGuard:
    """Apply the existing 15% loss rule around the unchanged fitted forest."""
    def __init__(self, estimator, loss_threshold=15.0):
        self.estimator = estimator
        self.classes_ = estimator.classes_
        self.loss_threshold = loss_threshold

    def predict_proba(self, features):
        import numpy as np
        features = np.asarray(features, dtype=float)
        probabilities = self.estimator.predict_proba(features).copy()
        overridden = features[:, 0] >= self.loss_threshold
        probabilities[overridden] = 0.0
        probabilities[overridden, list(self.classes_).index("degraded")] = 1.0
        return probabilities


class MLDetector:
    def __init__(self, model=MODEL, *, guard_loss=False):
        import joblib
        artifact = joblib.load(verify_model(model))
        if artifact.get("schema") != 1 or artifact.get("features") != FEATURES:
            raise ValueError("Incompatible model feature schema")
        if artifact["training_report"].get("kind") != "held_out_measured_validation":
            raise ValueError("Detector was not fitted from measured experiment data")
        self.artifact = artifact
        estimator = artifact["estimator"]
        self.estimator = LossGuard(estimator) if guard_loss else estimator
        self.column = list(self.estimator.classes_).index("degraded")

    def probability(self, observation):
        return float(self.estimator.predict_proba([observation.features()])[0, self.column])

    def unhealthy(self, observation):
        return self.probability(observation) >= self.artifact["threshold"]
