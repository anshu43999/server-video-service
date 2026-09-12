import argparse
import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "harness.py"
SPEC = importlib.util.spec_from_file_location("project_harness", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures/repo"


def fixture_state() -> dict:
    return {
        "schemaVersion": 1,
        "project": "test-project",
        "updatedAt": "2026-01-01T00:00:00+08:00",
        "majorTasks": [
            {
                "id": "M00",
                "title": "Test major",
                "status": "in_progress",
                "dependsOn": [],
                "acceptanceDocument": "harness/acceptance/M00.md",
                "acceptanceCriteria": ["All tests pass"],
                "subtasks": [
                    {
                        "id": "M00-T01",
                        "title": "First task",
                        "status": "completed",
                        "dependsOn": [],
                        "acceptance": "Record exists",
                        "record": "harness/records/M00/M00-T01.md",
                    }
                ],
            }
        ],
    }


class ValidateStateTest(unittest.TestCase):
    def test_valid_in_progress_state(self) -> None:
        self.assertEqual(
            [], harness.validate_state(fixture_state(), FIXTURE_ROOT)
        )

    def test_completed_task_requires_record(self) -> None:
        state = fixture_state()
        state["majorTasks"][0]["subtasks"][0]["record"] = (
            "harness/records/M00/missing.md"
        )
        errors = harness.validate_state(state, FIXTURE_ROOT)

        self.assertTrue(
            any("completed task record missing" in error for error in errors)
        )

    def test_missing_dependency_is_reported(self) -> None:
        state = fixture_state()
        task = state["majorTasks"][0]["subtasks"][0]
        task["status"] = "pending"
        task["dependsOn"] = ["M99-T99"]

        errors = harness.validate_state(state, FIXTURE_ROOT)

        self.assertTrue(any("missing dependency" in error for error in errors))

    def test_add_subtask_appends_pending_task_and_renders(self) -> None:
        state = fixture_state()
        args = argparse.Namespace(
            task_id="M00-T02",
            parent="M00",
            title="Follow-up task",
            acceptance="Follow-up acceptance",
            depends_on=["M00-T01"],
            record=None,
        )
        with mock.patch.object(harness, "save_state"), mock.patch.object(
            harness, "render_board"
        ):
            harness.command_add(state, args)
        task = state["majorTasks"][0]["subtasks"][-1]
        self.assertEqual("pending", task["status"])
        self.assertEqual(["M00-T01"], task["dependsOn"])
        self.assertEqual("harness/records/M00/M00-T02.md", task["record"])

    def test_add_subtask_rejects_duplicate_id(self) -> None:
        state = fixture_state()
        args = argparse.Namespace(
            task_id="M00-T01",
            parent="M00",
            title="Duplicate",
            acceptance="Nope",
            depends_on=[],
            record=None,
        )
        with self.assertRaises(harness.HarnessError):
            harness.command_add(state, args)

    def test_dependency_cycle_is_reported(self) -> None:
        state = fixture_state()
        first = state["majorTasks"][0]["subtasks"][0]
        first["status"] = "pending"
        first["dependsOn"] = ["M00-T02"]
        state["majorTasks"][0]["subtasks"].append(
            {
                "id": "M00-T02",
                "title": "Second task",
                "status": "pending",
                "dependsOn": ["M00-T01"],
                "acceptance": "Cycle fixture",
                "record": "harness/records/M00/M00-T02.md",
            }
        )

        errors = harness.validate_state(state, FIXTURE_ROOT)

        self.assertTrue(any("Dependency cycle" in error for error in errors))

    def test_completed_major_requires_passed_acceptance(self) -> None:
        state = fixture_state()
        major = state["majorTasks"][0]
        major["status"] = "completed"
        major["acceptanceDocument"] = "harness/acceptance/missing.md"

        errors = harness.validate_state(state, FIXTURE_ROOT)

        self.assertTrue(
            any("requires a passed acceptance" in error for error in errors)
        )

    def test_completed_major_with_passed_acceptance_is_valid(self) -> None:
        state = fixture_state()
        state["majorTasks"][0]["status"] = "completed"

        self.assertEqual([], harness.validate_state(state, FIXTURE_ROOT))

    def test_repo_path_escape_is_rejected(self) -> None:
        with self.assertRaises(harness.HarnessError):
            harness.safe_repo_path("../outside.md", FIXTURE_ROOT)


def state_with_retired_second_task(**overrides: object) -> dict:
    state = fixture_state()
    task = {
        "id": "M00-T02",
        "title": "Retired task",
        "status": "superseded",
        "dependsOn": [],
        "acceptance": "Void after the transport protocol change",
        "record": "harness/records/M00/M00-T02.md",
        "supersededReason": "transport protocol repositioning",
        "supersededAt": "2026-09-02T18:00:00+08:00",
    }
    task.update(overrides)
    state["majorTasks"][0]["subtasks"].append(task)
    return state


class SupersededValidationTest(unittest.TestCase):
    def test_superseded_task_needs_no_completion_record(self) -> None:
        state = state_with_retired_second_task()

        self.assertEqual([], harness.validate_state(state, FIXTURE_ROOT))

    def test_superseded_requires_a_reason(self) -> None:
        errors = harness.validate_state(
            state_with_retired_second_task(supersededReason=""), FIXTURE_ROOT
        )

        self.assertTrue(
            any("supersededReason is required" in error for error in errors)
        )

    def test_superseded_requires_a_timestamp(self) -> None:
        errors = harness.validate_state(
            state_with_retired_second_task(supersededAt=""), FIXTURE_ROOT
        )

        self.assertTrue(
            any("supersededAt is required" in error for error in errors)
        )

    def test_superseded_by_must_reference_a_known_task(self) -> None:
        errors = harness.validate_state(
            state_with_retired_second_task(supersededBy="M99-T99"), FIXTURE_ROOT
        )

        self.assertTrue(
            any("unknown supersededBy target" in error for error in errors)
        )

    def test_superseded_does_not_satisfy_a_dependency(self) -> None:
        state = state_with_retired_second_task()
        state["majorTasks"][0]["subtasks"][0]["dependsOn"] = ["M00-T02"]

        errors = harness.validate_state(state, FIXTURE_ROOT)

        self.assertTrue(
            any(
                "completed before dependency M00-T02" in error
                for error in errors
            )
        )

    def test_completed_major_allows_a_superseded_subtask(self) -> None:
        state = state_with_retired_second_task()
        state["majorTasks"][0]["status"] = "completed"

        self.assertEqual([], harness.validate_state(state, FIXTURE_ROOT))

    def test_completed_major_rejects_only_superseded_subtasks(self) -> None:
        state = state_with_retired_second_task()
        major = state["majorTasks"][0]
        major["status"] = "completed"
        major["subtasks"][0].update(
            {
                "status": "superseded",
                "supersededReason": "voided too",
                "supersededAt": "2026-09-02T18:00:00+08:00",
            }
        )

        errors = harness.validate_state(state, FIXTURE_ROOT)

        self.assertTrue(
            any("every subtask superseded" in error for error in errors)
        )

    def test_status_symbol_marks_superseded(self) -> None:
        self.assertEqual("[-]", harness.status_symbol("superseded"))


class SupersedeRecordTest(unittest.TestCase):
    def test_record_is_written_beside_the_completion_record(self) -> None:
        major = state_with_retired_second_task()["majorTasks"][0]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            record_path = harness.write_supersede_record(
                major["subtasks"][1],
                major,
                "transport protocol repositioning",
                "claude",
                superseded_by="M00-T01",
                previous_status="in_progress",
                repo_root=repo_root,
            )
            content = record_path.read_text(encoding="utf-8")
            untouched = repo_root / "harness/records/M00/M00-T02.md"

            self.assertTrue(record_path.name.startswith("M00-T02.superseded-"))
            self.assertFalse(untouched.exists())

        self.assertIn("status: superseded", content)
        self.assertIn("previous_status: in_progress", content)
        self.assertIn("superseded_by: M00-T01", content)
        self.assertIn("transport protocol repositioning", content)
        self.assertIn("Void after the transport protocol change", content)

    def test_record_without_a_replacement_says_so(self) -> None:
        major = state_with_retired_second_task()["majorTasks"][0]

        with tempfile.TemporaryDirectory() as temp_dir:
            record_path = harness.write_supersede_record(
                major["subtasks"][1],
                major,
                "scope voided",
                "claude",
                repo_root=Path(temp_dir),
            )
            content = record_path.read_text(encoding="utf-8")

        self.assertIn("superseded_by: none", content)
        self.assertIn("没有单一替代任务", content)


class SubtaskRecordLinkTest(unittest.TestCase):
    def test_existing_record_is_linked_directly(self) -> None:
        task = fixture_state()["majorTasks"][0]["subtasks"][0]

        link = harness.subtask_record_link(task, "M00", FIXTURE_ROOT)

        self.assertEqual("[M00-T01.md](../records/M00/M00-T01.md)", link)

    def test_supersede_variant_is_linked_when_record_is_absent(self) -> None:
        task = state_with_retired_second_task()["majorTasks"][0]["subtasks"][1]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            records = repo_root / "harness/records/M00"
            records.mkdir(parents=True)
            (records / "M00-T02.superseded-20260902-180000.md").write_text(
                "status: superseded\n", encoding="utf-8"
            )

            link = harness.subtask_record_link(task, "M00", repo_root)

        self.assertIn("../records/M00/M00-T02.superseded-", link)

    def test_missing_record_is_marked_pending(self) -> None:
        task = state_with_retired_second_task()["majorTasks"][0]["subtasks"][1]

        with tempfile.TemporaryDirectory() as temp_dir:
            link = harness.subtask_record_link(task, "M00", Path(temp_dir))

        self.assertEqual("待补充", link)


class SupersedeCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = fixture_state()
        self.state["majorTasks"][0]["subtasks"].append(
            {
                "id": "M00-T02",
                "title": "Retired task",
                "status": "in_progress",
                "dependsOn": [],
                "acceptance": "Void after the transport protocol change",
                "record": "harness/records/M00/M00-T02.md",
                "owner": "claude",
                "blocker": "waiting on the old transport decision",
                "blockedAt": "2026-09-01T10:00:00+08:00",
            }
        )

    @property
    def retired(self) -> dict:
        return self.state["majorTasks"][0]["subtasks"][1]

    @staticmethod
    def args(
        task_id: str, superseded_by: str | None = None
    ) -> argparse.Namespace:
        return argparse.Namespace(
            task_id=task_id,
            reason="transport protocol repositioning",
            owner="claude",
            superseded_by=superseded_by,
        )

    def run_supersede(self, args: argparse.Namespace) -> None:
        stub = harness.REPO_ROOT / "harness/records/M00/stub.md"
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
            harness, "save_state"
        ), mock.patch.object(harness, "render_board"), mock.patch.object(
            harness, "write_supersede_record", return_value=stub
        ):
            harness.command_supersede(self.state, args)

    def test_supersede_marks_the_task_and_clears_the_blocker(self) -> None:
        self.run_supersede(self.args("M00-T02"))

        self.assertEqual("superseded", self.retired["status"])
        self.assertEqual(
            "transport protocol repositioning",
            self.retired["supersededReason"],
        )
        self.assertTrue(self.retired["supersededAt"])
        self.assertNotIn("blocker", self.retired)
        self.assertNotIn("blockedAt", self.retired)
        self.assertEqual([], harness.validate_state(self.state, FIXTURE_ROOT))

    def test_supersede_records_a_replacement_task(self) -> None:
        self.run_supersede(self.args("M00-T02", superseded_by="M00-T01"))

        self.assertEqual("M00-T01", self.retired["supersededBy"])

    def test_completed_task_cannot_be_superseded(self) -> None:
        with self.assertRaises(harness.HarnessError):
            self.run_supersede(self.args("M00-T01"))

        self.assertEqual(
            "completed", self.state["majorTasks"][0]["subtasks"][0]["status"]
        )

    def test_major_task_cannot_be_superseded(self) -> None:
        with self.assertRaises(harness.HarnessError):
            self.run_supersede(self.args("M00"))

    def test_unknown_replacement_is_rejected(self) -> None:
        with self.assertRaises(harness.HarnessError):
            self.run_supersede(self.args("M00-T02", superseded_by="M99-T99"))

        self.assertEqual("in_progress", self.retired["status"])

    def test_task_cannot_supersede_itself(self) -> None:
        with self.assertRaises(harness.HarnessError):
            self.run_supersede(self.args("M00-T02", superseded_by="M00-T02"))

        self.assertEqual("in_progress", self.retired["status"])

    def test_superseded_task_cannot_be_started(self) -> None:
        self.run_supersede(self.args("M00-T02"))

        with self.assertRaises(harness.HarnessError):
            harness.command_start(
                self.state,
                argparse.Namespace(task_id="M00-T02", owner="claude"),
            )

        self.assertEqual("superseded", self.retired["status"])

    def test_superseded_task_cannot_be_blocked(self) -> None:
        self.run_supersede(self.args("M00-T02"))

        with self.assertRaises(harness.HarnessError):
            harness.command_block(
                self.state,
                argparse.Namespace(
                    task_id="M00-T02", reason="revive it", owner="claude"
                ),
            )

        self.assertEqual("superseded", self.retired["status"])


if __name__ == "__main__":
    unittest.main()
