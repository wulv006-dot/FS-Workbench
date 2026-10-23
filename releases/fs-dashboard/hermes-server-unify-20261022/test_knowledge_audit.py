import unittest

import test_native_knowledge  # Load the same source paths as native adapter checks.
from knowledge_audit import audit, READ_TOOLS


def event(seq, kind, payload, sid='test'):
    return {'params': {'seq': seq, 'type': kind, 'session_id': sid, 'payload': payload}}


class Audit(unittest.TestCase):
    def test_auditor_tool_ids_match_native_adapter_without_importing_its_dependencies(self):
        from fs_readonly.knowledge import READ_TOOLS as actual
        self.assertEqual(READ_TOOLS, actual)

    def test_failed_read_is_an_attempt_and_repeated_delivery_is_not_a_new_call(self):
        values = []
        for i, (name, status) in enumerate([('fs_get_knowledge_index', 'index_only'),
                                            ('fs_read_knowledge', 'missing_or_out_of_scope'),
                                            ('fs_read_knowledge', 'available')]):
            payload = dict(name=name, tool_id=str(i))
            values += [event(i * 2, 'tool.start', payload),
                       event(i * 2 + 1, 'tool.complete', dict(payload, result={'status': status}))]
        values += [event(6, 'message.complete', {'status': 'complete'}), values[3]]
        result = audit(values, 'test')
        self.assertEqual((result['attempts'], result['index_attempts'], result['content_attempts'],
                          result['content_successes'], result['failed_attempts']), (3, 1, 2, 1, 1))
        self.assertTrue(result['turn_complete'])

    def test_unfinished_calls_remain_unknown_and_other_sessions_are_excluded(self):
        values = [event(1, 'tool.start', {'name': 'fs_read_knowledge', 'tool_id': 'a'}),
                  event(1, 'tool.start', {'name': 'fs_read_knowledge', 'tool_id': 'b'}, sid='other')]
        result = audit(values, 'test')
        self.assertEqual(result['unknown_attempts'], 1)
        self.assertFalse(result['turn_complete'])

    def test_sequence_conflict_and_completion_without_start_are_rejected(self):
        a = event(1, 'tool.start', {'name': 'fs_read_knowledge', 'tool_id': 'a'})
        b = event(1, 'tool.start', {'name': 'fs_read_knowledge', 'tool_id': 'b'})
        with self.assertRaisesRegex(ValueError, 'sequence_conflict'):
            audit([a, b], 'test')
        with self.assertRaisesRegex(ValueError, 'start_missing'):
            audit([event(2, 'tool.complete', {'name': 'fs_read_knowledge', 'tool_id': 'a'})], 'test')


if __name__ == '__main__':
    unittest.main()
