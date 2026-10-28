"""Failback behavior, experiment accounting, and dashboard/CLI configuration."""
import io
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from dashboard.server import Runner, validate_config
from src.selfheal.cli import parser
from src.selfheal.config import ExperimentConfig
from src.selfheal.core import Observation, RecoveryPolicy, ThresholdDetector
from src.selfheal.experiment import summarize


def observations(**primary_changes):
    primary = Observation("primary", 0, 12, 0.2, 0.05)
    return {"primary": replace(primary, **primary_changes),
            "backup": Observation("backup", 0, 18, 0.2, 0.4)}


class PolicyTests(unittest.TestCase):
    def on_backup(self, **options):
        policy = RecoveryPolicy(ThresholdDetector(), **options)
        decision = policy.decide(observations(link_up=False, loss_pct=100, rtt_ms=None), 1)
        self.assertEqual((decision.destination, decision.reason), ("backup", "link_down"))
        # Decisions alone cannot change the selected route.
        self.assertEqual(policy.current, "primary")
        policy.commit(decision, 1)
        return policy

    def test_full_failure_repair_cycle_waits_then_commits(self):
        policy = self.on_backup()
        for now in (10, 11, 12, 14.99):
            decision = policy.decide(observations(), now)
            self.assertIsNone(decision.destination)
            self.assertEqual(decision.reason, "awaiting_primary_stability")
        decision = policy.decide(observations(), 15)
        self.assertEqual((decision.destination, decision.reason), ("primary", "primary_restored"))
        self.assertEqual(policy.current, "backup")
        policy.commit(decision, 15)
        self.assertEqual(policy.current, "primary")
        self.assertIsNone(policy.decide(observations(), 16).destination)

    def test_elapsed_time_alone_does_not_replace_required_observations(self):
        policy = self.on_backup()
        self.assertIsNone(policy.decide(observations(), 10).destination)
        self.assertIsNone(policy.decide(observations(), 20).destination)
        self.assertEqual(policy.decide(observations(), 21).destination, "primary")

    def test_bad_primary_window_restarts_the_entire_wait(self):
        for changes in ({"link_up": False}, {"loss_pct": 1}, {"rtt_ms": None},
                        {"rtt_ms": 40}, {"utilization": 0.90}):
            with self.subTest(changes=changes):
                policy = self.on_backup()
                for now in (10, 11, 12):
                    policy.decide(observations(), now)
                self.assertIsNone(policy.decide(observations(**changes), 15).destination)
                for now in (16, 17, 20.99):
                    self.assertIsNone(policy.decide(observations(), now).destination)
                self.assertEqual(policy.decide(observations(), 21).destination, "primary")

    def test_detector_must_also_approve_primary(self):
        policy = self.on_backup()
        policy.detector = Mock(unhealthy=lambda obs: obs.path == "primary")
        for now in (10, 11, 12, 20):
            self.assertIsNone(policy.decide(observations(), now).destination)

    def test_disabled_failback_retains_healthy_backup(self):
        policy = self.on_backup(failback=False)
        for now in (10, 11, 12, 100):
            self.assertIsNone(policy.decide(observations(), now).destination)
        self.assertEqual(policy.current, "backup")

    def test_backup_hard_failure_bypasses_stability_and_hold_down(self):
        for enabled in (True, False):
            with self.subTest(failback=enabled):
                policy = self.on_backup(failback=enabled, hold_down=100)
                obs = observations()
                obs["backup"] = replace(obs["backup"], link_up=False, loss_pct=100, rtt_ms=None)
                decision = policy.decide(obs, 2)
                self.assertEqual((decision.destination, decision.reason), ("primary", "link_down"))

    def test_backup_degradation_uses_existing_confirmation_rules(self):
        policy = self.on_backup()
        obs = observations()
        obs["backup"] = replace(obs["backup"], loss_pct=20)
        self.assertEqual(policy.decide(obs, 10).reason, "awaiting_confirmation")
        self.assertEqual(policy.decide(obs, 11).reason, "degradation")

    def test_both_paths_down_never_selects_an_alternative(self):
        policy = self.on_backup()
        obs = observations(link_up=False, loss_pct=100, rtt_ms=None)
        obs["backup"] = replace(obs["backup"], link_up=False)
        self.assertEqual(policy.decide(obs, 100).reason, "no_healthy_alternative")

    def test_failback_respects_hold_down(self):
        policy = self.on_backup(hold_down=20, failback_delay=0, failback_confirmations=1)
        self.assertEqual(policy.decide(observations(), 10).reason, "hold_down")
        self.assertEqual(policy.decide(observations(), 21).destination, "primary")

    def test_second_failure_requires_a_fresh_stability_wait(self):
        policy = self.on_backup()
        for now in (10, 11, 12):
            policy.decide(observations(), now)
        policy.commit(policy.decide(observations(), 15), 15)
        policy.commit(policy.decide(observations(link_up=False), 16), 16)
        self.assertEqual(policy.decide(observations(), 17).reason, "awaiting_primary_stability")
        self.assertIsNone(policy.decide(observations(), 21).destination)
        self.assertEqual(policy.decide(observations(), 22).destination, "primary")


class SummaryTests(unittest.TestCase):
    events = [
        {"event": "fault_on", "elapsed_s": 10},
        {"event": "route_change", "elapsed_s": 12, "source": "primary",
         "destination": "backup", "reason": "link_down"},
        {"event": "fault_off", "elapsed_s": 26},
        {"event": "route_change", "elapsed_s": 32, "source": "backup",
         "destination": "primary", "reason": "primary_restored"},
    ]

    def test_failback_accounted_separately_from_failover_recovery(self):
        rows = [{"path": "primary", "probe_start_s": now, "elapsed_s": now + 0.3,
                 "app_loss_pct": 0, "app_rtt_ms": 18} for now in (13, 14, 33)]
        result = summarize(ExperimentConfig(), rows, self.events, {})
        self.assertEqual(result["route_changes"], 2)
        self.assertEqual(result["failover_changes"], 1)
        self.assertEqual(result["automatic_failbacks"], 1)
        self.assertTrue(result["failback_observed"])
        self.assertEqual(result["fault_clear_to_failback_s"], 6)
        self.assertEqual(result["unnecessary_reroutes"], 0)
        self.assertAlmostEqual(result["verified_recovery_s"], 4.3)

    def test_only_failback_does_not_establish_failover_recovery(self):
        result = summarize(ExperimentConfig(), [], [self.events[i] for i in (0, 2, 3)], {})
        self.assertIsNone(result["detection_and_actuation_s"])
        self.assertFalse(result["recovery_observed"])

    def test_normal_and_both_down_do_not_claim_recovery(self):
        for scenario in ("normal", "both_down"):
            with self.subTest(scenario=scenario):
                result = summarize(replace(ExperimentConfig(), scenario=scenario), [], [], {})
                self.assertEqual(result["automatic_failbacks"], 0)
                self.assertIsNone(result["fault_clear_to_failback_s"])
                self.assertFalse(result["recovery_observed"])

    def test_early_failback_has_no_negative_fault_clear_latency(self):
        events = [dict(e, elapsed_s=20) if e.get("reason") == "primary_restored" else e
                  for e in self.events]
        result = summarize(ExperimentConfig(), [], events, {})
        self.assertTrue(result["failback_observed"])
        self.assertIsNone(result["fault_clear_to_failback_s"])

    def test_unplanned_post_fault_switch_still_counts_as_unnecessary(self):
        events = [dict(e, reason="degradation") if e.get("reason") == "primary_restored" else e
                  for e in self.events]
        result = summarize(ExperimentConfig(), [], events, {})
        self.assertEqual(result["automatic_failbacks"], 0)
        self.assertEqual(result["unnecessary_reroutes"], 1)


class ConfigurationTests(unittest.TestCase):
    base = {"scenario": "link_down", "topology": "long_diamond", "method": "threshold"}

    def test_defaults_and_cli_opt_out(self):
        self.assertTrue(ExperimentConfig().validate().failback)
        self.assertTrue(parser().parse_args(["demo"]).failback)
        args = parser().parse_args(["run", "--no-failback", "--failback-delay", "8",
                                    "--failback-confirmations", "4"])
        self.assertEqual((args.failback, args.failback_delay, args.failback_confirmations), (False, 8, 4))

    def test_invalid_runtime_and_dashboard_settings_rejected(self):
        for changes in ({"failback": "false"}, {"failback_delay": -1},
                        {"failback_delay": float("nan")}, {"failback_delay": float("inf")},
                        {"failback_delay": True}, {"failback_confirmations": 0},
                        {"failback_confirmations": 1.5}, {"failback_confirmations": True}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(ExperimentConfig(), **changes).validate()
                with self.assertRaises(ValueError):
                    validate_config(self.base | changes)

    def test_dashboard_propagates_policy_to_cli(self):
        for enabled in (True, False):
            with self.subTest(failback=enabled):
                config = validate_config(self.base | {"failback": enabled, "failback_delay": 8,
                                                       "failback_confirmations": 4})
                process = Mock(stdout=io.StringIO(""))
                process.wait.return_value = 0
                with patch("dashboard.server.subprocess.Popen", return_value=process) as popen:
                    Runner(live=True)._work([config])
                args = parser().parse_args(popen.call_args.args[0][3:])
                self.assertEqual((args.failback, args.failback_delay, args.failback_confirmations),
                                 (enabled, 8, 4))


if __name__ == "__main__":
    unittest.main()
