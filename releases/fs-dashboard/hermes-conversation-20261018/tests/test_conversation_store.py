import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from conversation_store import ConversationStore


class StoreTests(unittest.TestCase):
    def test_owner_idempotency_resume_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            conversation = store.create("admin_a")
            cid = conversation["conversation_id"]
            turn = store.reserve_turn("admin_a", cid, "查单品", "request_001")
            self.assertEqual(store.reserve_turn("admin_a", cid, "查单品", "request_001")["turn_id"], turn["turn_id"])
            with self.assertRaises(ValueError):
                store.reserve_turn("admin_a", cid, "换个问题", "request_001")
            with self.assertRaises(RuntimeError):
                store.reserve_turn("admin_a", cid, "并发追问", "request_002")
            run_id = "run_" + "a" * 32
            store.bind_run("admin_a", cid, turn["turn_id"], run_id)
            with self.assertRaises(LookupError):
                store.run("admin_b", cid, run_id)
            with self.assertRaises(LookupError):
                store.events("admin_b", cid)
            store.append_event("admin_a", cid, run_id, 0, {"event": "message.delta", "delta": "查", "reasoning": "secret"})
            store.append_event("admin_a", cid, run_id, 0, {"event": "message.delta", "delta": "查", "reasoning": "secret"})
            store.append_event("admin_a", cid, run_id, 1, {"event": "reasoning.available", "text": "hidden"})
            html = b"<!doctype html><html><script>parent.document.cookie</script></html>"
            store.append_event("admin_a", cid, run_id, 2, {"event": "run.completed", "output": html.decode()})
            store.set_state("admin_a", cid, turn["turn_id"], "completed")
            original = store.save_original("admin_a", cid, run_id, html, "hermes-original.html", "text/html")
            self.assertEqual(original["sha256"], hashlib.sha256(html).hexdigest())
            self.assertEqual(store.save_original("admin_a", cid, run_id, html, "hermes-original.html", "text/html"), original)
            self.assertEqual(store.artifact("admin_a", cid, original["artifact_id"])["content"], html)
            with self.assertRaises(LookupError):
                store.artifact("admin_b", cid, original["artifact_id"])
            with self.assertRaises(LookupError):
                store.artifact("admin_a", cid, "../conversations.db")
            events = store.events("admin_a", cid)
            self.assertEqual([e["type"] for e in events], ["message.delta", "run.completed"])
            self.assertEqual(store.events("admin_a", cid, events[0]["seq"])[0]["type"], "run.completed")
            self.assertNotIn("reasoning", str(events))
            snapshot = store.detail("admin_a", cid)
            self.assertEqual(snapshot["turns"][0]["text"], "查单品")
            self.assertEqual(snapshot["turns"][0]["reply"], html.decode())
            self.assertEqual(snapshot["last_seq"], events[-1]["seq"])

    def test_controls_do_not_repeat_unknown_external_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            cid = store.create("admin")["conversation_id"]
            turn = store.reserve_turn("admin", cid, "查询", "request_001")
            run_id = "run_" + "b" * 32
            store.bind_run("admin", cid, turn["turn_id"], run_id)
            first = store.action("admin", cid, run_id, "steer", "steer_001", "补充")
            second = store.action("admin", cid, run_id, "steer", "steer_001", "补充")
            self.assertFalse(first["reused"])
            self.assertEqual(second, {"state": "unknown", "reused": True})
            with self.assertRaises(ValueError):
                store.action("admin", cid, run_id, "stop", "steer_001")
            store.action_result("admin", cid, run_id, "steer_001", "accepted")
            self.assertEqual(store.action("admin", cid, run_id, "steer", "steer_001", "补充")["state"], "accepted")

    def test_running_snapshot_failure_and_sse_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            cid = store.create("admin")["conversation_id"]
            turn = store.reserve_turn("admin", cid, "先查销售", "request_001")
            run_id = "run_" + "c" * 32
            store.bind_run("admin", cid, turn["turn_id"], run_id)
            store.append_event("admin", cid, run_id, 0, {"event": "message.delta", "delta": "第一段"})
            store.append_event("admin", cid, run_id, None, {"event": "replay.truncated", "requested_seq": 0, "oldest_retained_seq": 2})
            store.append_event("admin", cid, run_id, 2, {"event": "message.delta", "delta": "第二段"})
            self.assertEqual(store.last_upstream("admin", cid, run_id), 2)
            self.assertEqual(store.detail("admin", cid)["turns"][0]["reply"], "第一段第二段")
            store.append_event("admin", cid, run_id, 3, {"event": "run.failed", "error": "已脱敏的错误", "secret": "hidden"})
            store.set_state("admin", cid, turn["turn_id"], "failed")
            self.assertEqual(store.detail("admin", cid)["turns"][0]["error"], "Hermes 运行失败，请检查任务状态")
            self.assertNotIn("已脱敏的错误", str(store.events("admin", cid)))
            self.assertNotIn("secret", str(store.events("admin", cid)))

    def test_terminal_dedup_after_many_events(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            cid = store.create("admin")["conversation_id"]
            turn = store.reserve_turn("admin", cid, "长运行", "request_001")
            run_id = "run_" + "d" * 32
            store.bind_run("admin", cid, turn["turn_id"], run_id)
            for seq in range(510):
                store.append_event("admin", cid, run_id, seq, {"event": "message.delta", "delta": "a"})
            store.append_event("admin", cid, run_id, 510, {"event": "run.completed", "output": "最终原文"})
            self.assertTrue(store.has_event("admin", cid, run_id, "run.completed"))
            self.assertEqual(store.detail("admin", cid)["turns"][0]["reply"], "最终原文")


if __name__ == "__main__":
    unittest.main()
