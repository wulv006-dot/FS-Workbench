"""Current DeepSeek policy and injected native-client contracts; no real API."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "source"))
from b1_model_routing import Capability, run_deepseek_task, select_model


class B1RuntimePolicy(unittest.TestCase):
    def setUp(self):
        self.caps = [Capability(p, p + "-fixture", frozenset({"text"}),
                               frozenset({"routine", "investigation"}),
                               tools=True, available=True)
                     for p in ("deepseek", "openai")]
        self.tools = [{"type": "function", "function": {
            "name": "mcp__fcro__get_data_catalog", "parameters": {
                "type": "object", "properties": {}, "additionalProperties": False}}}]
        self.request = {"model": "deepseek-fixture", "messages": [
            {"role": "user", "content": "synthetic investigation"}],
            "tools": self.tools, "reasoning_effort": "max", "enable_thinking": True}
        self.client = Mock(return_value={"status": "unknown", "provider_request_id": "original-native-id"})

    def run_task(self, **changes):
        args = dict(request_id="original-task:1", capabilities=self.caps,
                    task="investigation", inputs={"text"},
                    allowed_providers={"deepseek", "openai"}, request=self.request,
                    approved_tools=self.tools, request_model=self.client)
        args.update(changes)
        return run_deepseek_task(**args)

    def test_complex_runtime_task_invokes_only_deepseek(self):
        value = self.run_task()
        self.assertEqual(value["route"]["provider"], "deepseek")
        self.assertEqual(value["route"]["mode"], "deepseek_only")
        self.assertTrue(value["client_invoked"])
        self.client.assert_called_once_with(self.request, self.tools)

    def test_candidate_availability_does_not_enable_fallback(self):
        value = self.run_task(capabilities=[self.caps[1]])
        self.assertEqual(value["status"], "unavailable")
        self.assertFalse(value["client_invoked"])
        self.client.assert_not_called()

    def test_grants_and_actual_input_tool_capability_still_filter_deepseek(self):
        text_only = Capability("deepseek", "deepseek-fixture", frozenset({"text"}),
                               frozenset({"investigation"}), available=True)
        unavailable = Capability("deepseek", "deepseek-fixture", frozenset({"text"}),
                                 frozenset({"investigation"}), tools=True)
        for change in (dict(allowed_providers={"openai"}), dict(inputs={"image"}),
                       dict(capabilities=[text_only, self.caps[1]]),
                       dict(capabilities=[unavailable, self.caps[1]])):
            with self.subTest(change=change):
                self.assertEqual(self.run_task(**change)["status"], "unavailable")
        self.client.assert_not_called()

    def test_validation_mode_never_invokes_even_when_deepseek_wins(self):
        for task, expected in (("routine", "deepseek"), ("investigation", "openai")):
            with self.subTest(task=task):
                value = self.run_task(task=task, mode="contract_validation")
                self.assertEqual(value["status"], "validation_only")
                self.assertEqual(value["route"]["provider"], expected)
                self.assertFalse(value["route"]["invocation_allowed"])
                self.assertFalse(value["client_invoked"])
        self.client.assert_not_called()

    def test_native_model_mismatch_is_rejected_before_call(self):
        with self.assertRaisesRegex(ValueError, "native_model_mismatch"):
            self.run_task(request=dict(self.request, model="openai-fixture"))
        self.client.assert_not_called()

    def test_request_tools_deadline_and_identity_are_not_rewritten(self):
        original = deepcopy(self.request)
        deadline = datetime(2026, 11, 1, tzinfo=timezone.utc)
        def native(request, tools, *, deadline):
            self.assertEqual(request, original)
            self.assertEqual(tools, self.tools)
            request["messages"][0]["content"] = "client-private-mutation"
            tools.clear()
            return {"status": "unknown", "provider_request_id": "original-native-id"}
        self.client.side_effect = native
        value = self.run_task(deadline=deadline)
        self.client.assert_called_once()
        self.assertEqual(self.client.call_args.kwargs["deadline"], deadline)
        self.assertEqual(self.request, original)
        self.assertEqual(value["request_id"], "original-task:1")
        self.assertEqual(value["provider_result"]["provider_request_id"], "original-native-id")
        self.assertFalse(value["retry_allowed"])
        self.assertFalse(value["fallback_performed"])
        self.assertNotIn("client-private-mutation", str(value))

    def test_transport_unknown_never_retries_or_exposes_exception(self):
        for error in (TimeoutError, ConnectionError, OSError):
            with self.subTest(error=error):
                client = Mock(side_effect=error("PRIVATE_TRANSPORT_DETAIL"))
                value = self.run_task(request_model=client)
                self.assertEqual(value["status"], "unknown")
                self.assertEqual(value["request_id"], "original-task:1")
                self.assertFalse(value["retry_allowed"])
                self.assertFalse(value["fallback_performed"])
                self.assertNotIn("PRIVATE_TRANSPORT_DETAIL", str(value))
                client.assert_called_once()

    def test_provider_rejections_and_deadline_are_not_task_success(self):
        for state in ("configuration_missing", "configuration_invalid", "scheduled_deadline",
                      "unknown", "partial", "model_capability_changed"):
            with self.subTest(state=state):
                reply = {"status": state, "provider_request_id": "native-id"}
                value = self.run_task(request_model=Mock(return_value=reply))
                self.assertEqual(value["status"], state)
                self.assertEqual(value["provider_result"], reply)
                self.assertFalse(value["retry_allowed"])
                self.assertFalse(value["fallback_performed"])

    def test_unlabelled_response_is_not_called_completed(self):
        value = self.run_task(request_model=Mock(return_value={"model": "deepseek-fixture", "id": "native"}))
        self.assertEqual(value["status"], "provider_returned")
        self.assertNotIn("task_completed", value)
        invalid = self.run_task(request_model=Mock(return_value=None))
        self.assertEqual(invalid["status"], "invalid_response")

    def test_invalid_mode_and_request_fail_before_invocation(self):
        for change in (dict(mode="live_openai"), dict(request_id=""),
                       dict(request=[]), dict(request=dict(self.request, tools="untrusted")),
                       dict(approved_tools={})):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_task(**change)
        self.client.assert_not_called()

    def test_real_native_payload_contract_with_mock_transport(self):
        spec = importlib.util.spec_from_file_location("b1_runtime_native_fixture", HERE / "source/direct_provider.py")
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        caps = [Capability("deepseek", native.MODEL, frozenset({"text"}),
                           frozenset({"investigation"}), tools=True, available=True), self.caps[1]]
        request = dict(self.request, model=native.MODEL, max_tokens=native.OUTPUT_TOKENS,
                       tool_choice="auto", stream=False)
        reply = {"id": "synthetic-native-response", "model": native.MODEL,
                 "reasoning_effort": "max", "choices": []}
        deadline = datetime.now(timezone.utc) + timedelta(minutes=1)
        with patch.object(native, "_open", return_value=reply) as transport:
            value = self.run_task(capabilities=caps, request=request,
                                  request_model=native.request_model, deadline=deadline)
        transport.assert_called_once()
        path, payload = transport.call_args.args
        encoded = json.loads(payload)
        self.assertEqual(path, "/chat/completions")
        self.assertEqual(encoded["model"], native.MODEL)
        self.assertEqual(encoded["reasoning_effort"], "max")
        self.assertEqual(encoded["thinking"], {"type": "enabled"})
        self.assertEqual(encoded["max_tokens"], native.OUTPUT_TOKENS)
        self.assertEqual(encoded["tools"], self.tools)
        self.assertEqual(transport.call_args.kwargs["deadline"], deadline)
        self.assertNotIn("request_id", encoded)
        self.assertNotIn("mode", encoded)
        self.assertEqual(value["provider_result"]["id"], "synthetic-native-response")
        self.assertEqual(value["status"], "provider_returned")


if __name__ == "__main__":
    unittest.main()
