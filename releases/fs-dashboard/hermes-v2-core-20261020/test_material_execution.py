"""Actual B frozen payload and capability boundary; no model or runtime client."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent / "source"))
from b1_model_routing import handoff
from conversation_file_tools import NAMES, attach_conversation_file_tools, file_prompt, tool_schemas
from material_execution import (freeze_execution, validate_execution, operation_guard, prepare_materials,
                                build_context_proof, verify_context_proof)
from conversation_file_tools import WIRE_NAMES

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
FID = "a" * 32


class MaterialExecutionTests(unittest.TestCase):
    def arguments(self):
        request = "material_request_001"
        return dict(binding=dict(owner="alice", cid="cid", goal_id="goal", scope_ref="materials:grant-1",
                                 request_id=request, intent_sha256="f" * 64),
                    handoff=handoff(task_id=request, revision=2, goal="核查明确选择的表",
                                    constraints=["只读"], evidence=[], completed_actions=[], next_step="读取必要页"),
                    selection_revision=1, files=[dict(file_id=FID, sha256="b" * 64, parent_id=None,
                        version=1, size=91, expires_at=(NOW + timedelta(days=1)).timestamp())],
                    operation={"mode": "read"}, deadline_at=NOW + timedelta(minutes=5), now=NOW)

    def frozen(self, **updates):
        args = self.arguments()
        args.update(updates)
        return freeze_execution(**args)

    def revise(self):
        return {"mode": "revise", "file_id": FID, "edits": [dict(sheet=0, row=1, column=1, value=25)], "format": "xlsx"}

    def revise_args(self, fixed):
        op = fixed["operation"]
        return {k: deepcopy(op[k]) for k in ("file_id", "edits", "format")} | {"request_id": op["revision_request_id"]}

    def test_freeze_does_not_mutate_inputs_or_load_content(self):
        args = self.arguments()
        args["files"][0].update(content="PRIVATE CELLS", filename="private.csv", path="PRIVATE PATH")
        before = deepcopy(args)
        value = freeze_execution(**args)
        self.assertEqual(args, before)
        text = json.dumps(value, ensure_ascii=False)
        self.assertNotIn("PRIVATE", text)
        self.assertNotIn("expires_at", value["input"])
        self.assertEqual(value["manifest"]["files"][0]["file_id"], FID)
        self.assertEqual(validate_execution(value, now=NOW), value)

    def test_canonical_selection_order_and_clock_do_not_create_new_intent(self):
        args = self.arguments()
        args["files"].append(dict(args["files"][0], file_id="c" * 32))
        first = freeze_execution(**args)
        args["files"].reverse()
        args["now"] += timedelta(seconds=1)
        self.assertEqual(freeze_execution(**args), first)

    def test_payload_binds_full_selection_operation_and_handoff_not_only_logical_digest(self):
        first = self.frozen()
        for key in ("sha256", "version", "size", "expires_at"):
            args = self.arguments()
            args["files"][0][key] = "c" * 64 if key == "sha256" else args["files"][0][key] + 1
            other = freeze_execution(**args)
            self.assertNotEqual(other["payload_sha256"], first["payload_sha256"])
            self.assertNotEqual(other["snapshot_id"], first["snapshot_id"])
        changed = self.arguments()["handoff"]
        changed["next_step"] = "只核第一张sheet"
        second = self.frozen(handoff=changed)
        self.assertNotEqual(first["knowledge_version"], second["knowledge_version"])
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])

    def test_recomputed_payload_checksum_cannot_hide_frozen_context_or_template_drift(self):
        first = self.frozen()
        for key in ("kind", "snapshot_id", "system_prompt", "input", "template_version", "knowledge_version"):
            value = deepcopy(first)
            value[key] += "changed"
            body = {k: v for k, v in value.items() if k != "payload_sha256"}
            value["payload_sha256"] = hashlib.sha256(json.dumps(body, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_execution(value, now=NOW)

    def test_read_does_not_authorize_revision_but_leaves_generated_membership_to_a(self):
        fixed = self.frozen()
        for name, args in ((NAMES[0], {}), (NAMES[1], dict(file_id="d" * 32, sheet=0, offset=0, limit=200))):
            self.assertIs(operation_guard(fixed, name, args, now=NOW), True)
        with self.assertRaises(PermissionError):
            operation_guard(fixed, NAMES[2], self.revise_args(self.frozen(operation=self.revise())), now=NOW)

    def test_revision_exact_cells_format_file_and_original_request_are_enforced(self):
        fixed = self.frozen(operation=self.revise())
        args = self.revise_args(fixed)
        self.assertIs(operation_guard(fixed, NAMES[2], args, now=NOW), True)
        mutations = [dict(args, file_id="e" * 32), dict(args, format="csv"),
                     dict(args, request_id="another_revision"), dict(args, edits=[dict(args["edits"][0], value=30)]),
                     dict(args, edits=[dict(args["edits"][0], value=True)])]
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(PermissionError):
                operation_guard(fixed, NAMES[2], changed, now=NOW)

    def test_revision_identity_is_stable_and_changes_with_request_or_operation(self):
        first = self.frozen(operation=self.revise())
        self.assertEqual(self.frozen(operation=self.revise()), first)
        args = self.arguments()
        args["operation"] = self.revise()
        args["binding"]["request_id"] = args["handoff"]["task_id"] = "material_request_002"
        self.assertNotEqual(freeze_execution(**args)["operation"]["revision_request_id"], first["operation"]["revision_request_id"])
        op = self.revise()
        op["edits"][0]["value"] = 30
        self.assertNotEqual(self.frozen(operation=op)["operation"]["revision_request_id"], first["operation"]["revision_request_id"])

    def test_prepare_versions_actual_scope_selection_and_operation_without_fake_work(self):
        args = self.arguments()
        def prepare(**changes):
            values = dict(owner="alice", cid="cid", scope_ref="materials:grant-1", selection_revision=1,
                          files=args["files"], operation=args["operation"], now=NOW)
            values.update(changes)
            return prepare_materials(**values)
        prepared = prepare()
        self.assertEqual(prepared["fact_version"], self.frozen()["fact_version"])
        self.assertEqual(prepare(now=NOW + timedelta(seconds=1)), prepared)
        for change in (dict(scope_ref="materials:grant-2"), dict(owner="bob"), dict(cid="other"),
                       dict(selection_revision=2), dict(operation=self.revise())):
            self.assertNotEqual(prepare(**change)["fact_version"], prepared["fact_version"])
        frozen = self.frozen(operation=self.revise())
        self.assertEqual(prepare(operation=self.revise())["fact_version"], frozen["fact_version"])
        self.assertNotIn("request_id", json.dumps(prepared))

    def test_bad_selection_metadata_and_expired_source_fail_before_runtime(self):
        for change, error in ((dict(version=True), ValueError), (dict(size=-1), ValueError),
                (dict(sha256="x"), ValueError), (dict(expires_at=True), ValueError),
                (dict(expires_at=float("nan")), ValueError), (dict(status="missing"), PermissionError),
                (dict(expires_at=NOW.timestamp()), PermissionError)):
            files = self.arguments()["files"]
            files[0].update(change)
            with self.subTest(change=change), self.assertRaises(error):
                self.frozen(files=files)
        for files in ([], self.arguments()["files"] * 2, self.arguments()["files"] * 11):
            with self.assertRaises(ValueError):
                self.frozen(files=files)

    def test_original_binding_handoff_identity_and_size_are_checked(self):
        args = self.arguments()
        args["handoff"]["task_id"] = "other_request"
        with self.assertRaises(ValueError):
            freeze_execution(**args)
        for key, value in (("owner", "alice\nadmin"), ("intent_sha256", "bad")):
            args = self.arguments()
            args["binding"][key] = value
            with self.assertRaises(ValueError):
                freeze_execution(**args)
        minimal = self.arguments()["handoff"]
        minimal["raw_chat"] = "private"
        with self.assertRaises(ValueError):
            self.frozen(handoff=minimal)
        minimal.pop("raw_chat")
        minimal["goal"] = "目标" * 16000
        with self.assertRaises(ValueError):
            self.frozen(handoff=minimal)

    def test_deadline_is_aware_and_rechecked_on_every_operation(self):
        fixed = self.frozen()
        with self.assertRaises(PermissionError):
            operation_guard(fixed, NAMES[0], {}, now=NOW + timedelta(minutes=5))
        for at in (NOW.replace(tzinfo=None), "2026-11-01T00:05:00"):
            with self.assertRaises(ValueError):
                self.frozen(deadline_at=at)
        args = self.arguments()
        args["files"][0]["expires_at"] = (NOW + timedelta(seconds=5)).timestamp()
        fixed = freeze_execution(**args)
        with self.assertRaises(PermissionError):
            operation_guard(fixed, NAMES[0], {}, now=NOW + timedelta(seconds=6))

    def test_integrity_only_validation_allows_cleanup_but_never_disables_tool_liveness(self):
        fixed = self.frozen()
        self.assertEqual(validate_execution(fixed), fixed)
        with self.assertRaises(PermissionError):
            validate_execution(fixed, now=NOW + timedelta(days=2))
        with self.assertRaises(ValueError):
            operation_guard(fixed, NAMES[0], {}, now=None)
        args = self.arguments()
        args["now"] = None
        with self.assertRaises(ValueError):
            freeze_execution(**args)

    def test_unselected_or_implicit_revision_and_non_file_tools_are_denied(self):
        for op in (dict(self.revise(), file_id="f" * 32),):
            with self.assertRaises(PermissionError):
                self.frozen(operation=op)
        for op in (dict(self.revise(), edits=[]), {"mode": "read", "url": "https://invalid"},
                   dict(self.revise(), edits=[dict(sheet=0, row=1, column=1, value=float("nan"))])):
            with self.assertRaises(ValueError):
                self.frozen(operation=op)
        with self.assertRaises(PermissionError):
            operation_guard(self.frozen(), "fs.pricing.control", {}, now=NOW)

    def proof_inputs(self, fixed):
        return dict(session_id="material_fixture_session", run_id="run_" + "1" * 32,
                    actual_system_prompt="native fixture prelude\n" + fixed["system_prompt"] + "\nfixture tool map",
                    actual_input=fixed["input"], actual_tool_names=list(WIRE_NAMES), native_memory_skipped=True)

    def test_context_measurements_bind_real_identifiers_and_store_only_hashes(self):
        fixed = self.frozen()
        observations = self.proof_inputs(fixed)
        proof = build_context_proof(fixed, **observations)
        self.assertIs(verify_context_proof(fixed, proof,
            session_id=observations["session_id"], run_id=observations["run_id"]), True)
        self.assertNotIn("native fixture", json.dumps(proof))
        self.assertNotIn(fixed["handoff"]["goal"], json.dumps(proof, ensure_ascii=False))
        self.assertEqual(proof["system_prompt_sha256"],
                         hashlib.sha256(observations["actual_system_prompt"].encode()).hexdigest())

    def test_context_measurements_reject_missing_prompt_changed_input_tools_and_memory(self):
        fixed = self.frozen()
        for change in (dict(actual_system_prompt="unrelated prompt"), dict(actual_input="other request"),
                       dict(actual_tool_names=list(WIRE_NAMES) + ["fs.pricing.control"]),
                       dict(actual_tool_names=[WIRE_NAMES[0]] * 3), dict(native_memory_skipped=1),
                       dict(native_memory_skipped=False)):
            with self.subTest(change=change), self.assertRaises(PermissionError):
                build_context_proof(fixed, **dict(self.proof_inputs(fixed), **change))

    def test_context_proof_rejects_cross_run_scope_payload_and_truthy_measurement_flags(self):
        fixed = self.frozen()
        observed = self.proof_inputs(fixed)
        proof = build_context_proof(fixed, **observed)
        def verify(value, **changes):
            return verify_context_proof(fixed, value,
                **dict(session_id=observed["session_id"], run_id=observed["run_id"], **changes))
        with self.assertRaises(PermissionError):
            verify_context_proof(fixed, proof, session_id="other", run_id=observed["run_id"])
        with self.assertRaises(PermissionError):
            verify_context_proof(fixed, proof, session_id=observed["session_id"], run_id="run_" + "2" * 32)
        for key, value in (("input_sha256", "a" * 64), ("payload_sha256", "b" * 64),
                           ("prompt_present", 1), ("input_verified", "yes"), ("native_memory_skipped", False)):
            with self.subTest(key=key), self.assertRaises(PermissionError):
                verify(dict(proof, **{key: value}))
        with self.assertRaises(PermissionError):
            verify(dict(proof, model_body="model says complete"))


class ExecutionToolsTests(unittest.TestCase):
    def test_material_evidence_labels_do_not_inherit_turn_scope_or_business_freshness(self):
        context = Mock()
        context.read_table.return_value = dict(file_id=FID, sha256="b" * 64, complete=True,
            next_offset=None, sheets=[dict(rows=[["fixture"]])],
            coverage=dict(scope="selected_sheet", sheet=0, offset=0, end_exclusive=1,
                          total_rows=1, returned_rows=1, total_sheets=1, complete=True))
        book = SimpleNamespace(call=Mock())
        attach_conversation_file_tools(book, context, scope="material_execution_files", operation_guard=lambda *args: True)
        value = book.call(NAMES[1], dict(file_id=FID, sheet=0, offset=0, limit=200))
        self.assertEqual(value["analysis_coverage"]["scope"], "this_execution_observed_pages")
        self.assertEqual(value["analysis_coverage"]["time_basis"], "tool_read_receipt_not_business_data_date")
        refs = book.material_evidence.handoff_evidence()
        self.assertEqual(refs[0]["source"], "material_execution_files")
        self.assertEqual(set(refs[0]["missing"]), {"business_data_not_read", "long_term_goal_not_assessed"})

    def test_scope_is_static_host_input_not_a_model_schema_argument(self):
        context = Mock()
        prompt = file_prompt(context, scope="material_execution_files")
        self.assertIn("当前材料执行", prompt)
        self.assertNotIn("当前turn", prompt)
        self.assertEqual(context.mock_calls, [])
        self.assertIn("当前turn", file_prompt())
        for schema in tool_schemas(scope="material_execution_files"):
            self.assertNotIn("scope", schema["function"]["parameters"]["properties"])
        with self.assertRaises(ValueError):
            tool_schemas(scope="global")

    def test_material_scope_requires_guard_and_denies_bypass_before_original_book(self):
        original, context = Mock(), Mock()
        book = SimpleNamespace(call=original)
        with self.assertRaises(ValueError):
            attach_conversation_file_tools(book, context, scope="material_execution_files")
        attach_conversation_file_tools(book, context, scope="material_execution_files", operation_guard=lambda *args: True)
        with self.assertRaises(PermissionError):
            book.call("fs.pricing.control", {})
        original.assert_not_called()
        self.assertEqual(context.mock_calls, [])

    def test_guard_must_be_literal_true_and_data_instructions_never_change_it(self):
        for decision in (False, 1, "allowed", None):
            original, context = Mock(), Mock()
            book = SimpleNamespace(call=original)
            attach_conversation_file_tools(book, context, scope="material_execution_files",
                                           operation_guard=lambda *args: decision)
            with self.assertRaises(PermissionError):
                book.call(NAMES[0], {})
            self.assertEqual(context.mock_calls, [])

    def test_actual_frozen_operation_guard_is_consumed_before_a_and_unknown_is_not_retried(self):
        fixture = MaterialExecutionTests()
        fixed = fixture.frozen(operation=fixture.revise())
        context = Mock()
        context.revise.return_value = {"status": "unknown", "request_id": fixed["operation"]["revision_request_id"]}
        book = SimpleNamespace(call=Mock())
        attach_conversation_file_tools(book, context, scope="material_execution_files",
            operation_guard=lambda name, args: operation_guard(fixed, name, args, now=NOW))
        args = fixture.revise_args(fixed)
        result = book.call(NAMES[2], args)
        self.assertEqual(result["scope"], "material_execution_files")
        self.assertEqual(result["status"], "unknown")
        context.revise.assert_called_once()
        with self.assertRaises(PermissionError):
            book.call(NAMES[2], dict(args, format="csv"))
        context.revise.assert_called_once()


if __name__ == "__main__":
    unittest.main()
