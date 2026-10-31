"""Offline contracts: never construct a network client or load credentials."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).parent / "source"))
from b1_model_routing import Capability, DeepSeekAdapter, OpenAIAdapter, handoff, select_model


class B1Contracts(unittest.TestCase):
    def route(self, **changes):
        args = dict(task="routine", inputs={"text"}, needs_tools=False,
                    allowed_providers={"deepseek", "openai"})
        args.update(changes)
        caps = [Capability(p, p+"-fixture", frozenset({"text"}),
                           frozenset({"routine", "investigation"}), available=True)
                for p in ("openai", "deepseek")]
        return select_model(caps, **args)

    def test_routine_retains_deepseek(self):
        self.assertEqual(self.route()["provider"], "deepseek")

    def test_complex_defaults_to_deepseek_until_formal_switch(self):
        self.assertEqual(self.route(task="investigation")["provider"], "deepseek")

    def test_complex_can_validate_openai_without_enabling_invocation(self):
        value = self.route(task="investigation", mode="contract_validation")
        self.assertEqual(value["provider"], "openai")
        self.assertFalse(value["invocation_allowed"])

    def test_grants_precede_preference(self):
        self.assertEqual(self.route(task="investigation", allowed_providers={"deepseek"})["provider"], "deepseek")

    def test_unsupported_tools_images_and_no_grant(self):
        for change in ({"needs_tools": True}, {"inputs": {"image"}}, {"allowed_providers": set()}):
            self.assertEqual(self.route(**change)["status"], "unavailable")

    def test_unknown_capability_not_available_by_default(self):
        c = Capability("openai", "fixture", frozenset({"text"}), frozenset({"routine"}))
        self.assertEqual(select_model([c], task="routine", inputs={"text"}, needs_tools=False,
                                      allowed_providers={"openai"})["status"], "unavailable")

    def test_deepseek_preserves_native_contract_and_deadline(self):
        request = {"model": "deepseek-flash", "reasoning_effort": "max", "enable_thinking": True}
        client = Mock(return_value={"status": "unknown", "provider_response_id": "old-id"})
        adapter = DeepSeekAdapter(client)
        self.assertEqual(adapter.invoke(request, [], deadline=123)["status"], "unknown")
        client.assert_called_once_with(request, [], deadline=123)
        adapter.invoke(request, [])
        self.assertEqual(client.call_count, 2)
        self.assertNotIn("deadline", client.call_args.kwargs)

    def response(self):
        return dict(id="resp_fixture", model="fixture-model", status="completed",
                    output=[dict(type="message", role="assistant", content=[dict(type="output_text", text="answer")])],
                    usage=dict(input_tokens=10, output_tokens=7, total_tokens=17,
                               output_tokens_details={"reasoning_tokens": 5}))

    def invoke(self, result):
        client = Mock(return_value=result)
        value = OpenAIAdapter(client, "fixture-model").invoke(request_id="task-1:1", text="summary", max_output_tokens=100)
        client.assert_called_once_with(model="fixture-model", input="summary", store=False, max_output_tokens=100)
        return value

    def test_openai_usage_not_double_counted_or_priced(self):
        result = self.invoke(self.response())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["usage"]["total_tokens"], 17)
        self.assertIsNone(result["cost"])
        self.assertEqual(result["verification"], "local_contract_only")

    def test_missing_usage_is_unknown_not_zero(self):
        response = self.response(); response.pop("usage")
        self.assertIsNone(self.invoke(response)["usage"])

    def test_timeout_does_not_retry_or_fallback(self):
        client = Mock(side_effect=TimeoutError("private transport details"))
        value = OpenAIAdapter(client, "fixture-model").invoke(request_id="same-id", text="summary", max_output_tokens=1)
        self.assertEqual(value["status"], "unknown")
        self.assertEqual(value["request_id"], "same-id")
        self.assertFalse(value["retry_allowed"])
        self.assertNotIn("private", str(value)); client.assert_called_once()

    def test_partial_refusal_tool_and_malformed_not_success(self):
        changes = [{"status": "incomplete"}, {"model": "different"}, {"output": []},
                   {"output": [{"type": "function_call"}]}, {"usage": {"input_tokens": True}},
                   {"output": [{"type": "message", "role": "assistant", "content": [{"type": "refusal"}]}]}]
        for change in changes:
            with self.subTest(change=change):
                self.assertNotEqual(self.invoke(dict(self.response(), **change))["status"], "completed")

    def test_validation_before_dispatch(self):
        client = Mock()
        with self.assertRaises(ValueError):
            OpenAIAdapter(client, "fixture").invoke(request_id="", text="x", max_output_tokens=1)
        client.assert_not_called()

    def test_provider_unknown_keeps_request_identity(self):
        value = self.invoke(dict(self.response(), status="unknown"))
        self.assertEqual(value["status"], "unknown")
        self.assertEqual(value["request_id"], "task-1:1")
        self.assertFalse(value["retry_allowed"])

    def test_handoff_retains_partial_evidence_and_actions_without_aliasing(self):
        evidence = [dict(ref="ev-1", source="Admin", as_of="2026-10-31", coverage="partial",
                         missing=["refunds"], version="v1")]
        args = dict(task_id="t1", revision=1, goal="investigate", constraints=["read only"],
                    evidence=evidence, completed_actions=["operation-1"], next_step="query coverage")
        value = handoff(**args); evidence[0]["missing"].append("cost")
        self.assertEqual(value["evidence"][0]["missing"], ["refunds"])
        self.assertEqual(value["completed_actions"], ["operation-1"])
        with self.assertRaises(ValueError):
            handoff(**dict(args, evidence=[dict(evidence[0], private_reasoning="no")]))
        with self.assertRaises(ValueError):
            handoff(**dict(args, goal="x" * 40000))


if __name__ == "__main__":
    unittest.main()
