import unittest

from app.alerts.lifecycle import EventStateMachine


class EventLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.rule = {
            "ruleId": "crowd", "ruleVersion": 3, "operator": "COUNT",
            "thresholds": {"minConsecutiveFrames": 2, "cooldownMs": 1000},
            "escalation": {"escalateAfterMs": 300, "toSeverity": "CRITICAL"},
        }

    def hit(self, ts, severity="MINOR", value=3):
        return {"sourceId": "cam-1", "subjectKey": "roi:yard", "capturedAtUs": ts,
                "severity": severity, "measuredValue": value}

    def test_candidate_confirmation_and_snapshot_fields(self):
        machine = EventStateMachine()
        candidate = machine.on_hit(self.rule, self.hit(1000), candidate_frames=1)
        self.assertEqual(candidate.state, "CANDIDATE")
        confirmed = machine.on_hit(self.rule, self.hit(2000), candidate_frames=2)
        self.assertEqual(confirmed.state, "CONFIRMED")
        self.assertEqual(confirmed.started_at_us, 1000)
        self.assertEqual(confirmed.rule_version, 3)
        self.assertEqual(confirmed.subject_key, "roi:yard")
        self.assertEqual(confirmed.effective_thresholds["cooldownMs"], 1000)

    def test_same_level_cooldown_suppresses_but_upgrade_passes(self):
        machine = EventStateMachine()
        first = machine.on_hit(self.rule, self.hit(1000), confirmed=True)
        machine.on_condition_lost("crowd", "cam-1", "roi:yard", 1100)
        suppressed = machine.on_hit(self.rule, self.hit(1500), confirmed=True)
        self.assertEqual(suppressed.event_id, first.event_id)
        self.assertEqual(suppressed.suppressed_count, 1)
        upgraded = machine.on_hit(self.rule, self.hit(1600, "MAJOR", 8), confirmed=True)
        self.assertNotEqual(upgraded.event_id, first.event_id)
        self.assertEqual(upgraded.severity, "MAJOR")

    def test_condition_loss_and_monotonic_time(self):
        machine = EventStateMachine()
        event = machine.on_hit(self.rule, self.hit(1000), confirmed=True)
        ended = machine.on_condition_lost("crowd", "cam-1", "roi:yard", 2000)
        self.assertTrue(any(e.event_id == event.event_id for e in ended))
        with self.assertRaises(ValueError):
            machine.on_hit(self.rule, self.hit(1500), confirmed=True)

    def test_unattended_escalation_does_not_change_fact_severity(self):
        machine = EventStateMachine()
        event = machine.on_hit(self.rule, self.hit(1000), confirmed=True)
        changed = machine.escalate_unattended(301000)
        self.assertEqual(changed[0].severity, "MINOR")
        self.assertEqual(changed[0].notify_severity, "CRITICAL")
        self.assertEqual(changed[0].escalated_at_us, 301000)
        self.assertEqual(machine.escalate_unattended(500000), [])

    def test_acknowledge_stops_escalation(self):
        machine = EventStateMachine()
        event = machine.on_hit(self.rule, self.hit(1000), confirmed=True)
        machine.acknowledge(event.event_id, "operator", 1100)
        self.assertEqual(machine.escalate_unattended(400000), [])


if __name__ == "__main__":
    unittest.main()
