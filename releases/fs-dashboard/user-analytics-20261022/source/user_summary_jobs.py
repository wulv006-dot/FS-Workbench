"""Bounded continuation for cold connector summaries."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
import re
from secrets import token_hex
from threading import Lock


class SummaryJobs:
    def __init__(self, query):
        self.query = query
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fs-user-summary')
        self.lock = Lock()
        self.jobs = OrderedDict()

    def read(self, args, user, *, wait_seconds=3):
        if 'query_id' in args:
            query_id = args['query_id']
            if set(args) != {'query_id'} or (not isinstance(query_id, str) or not re.fullmatch(r'[0-9a-f]{32}', query_id)):
                raise ValueError('users_summary_query_id')
            with self.lock:
                job = self.jobs.get(query_id)
                if job is None or job[0] != user:
                    return 404, {'error': 'users_summary_query_expired'}
                future = job[2]
            return self.reply(query_id, future, user)

        if args.get('snapshot_id'):
            return 200, self.query(args, user)

        created = False
        with self.lock:
            for query_id, (owner, query, future) in self.jobs.items():
                if not future.done():
                    if owner != user or query != args:
                        return 429, {'error': 'users_summary_busy', 'retryAfter': 5}
                    break
            else:
                created = True
                query_id = token_hex(16)
                future = self.pool.submit(self.run, args.copy(), user)
                self.jobs[query_id] = (user, args.copy(), future)
                if len(self.jobs) > 8:
                    self.jobs.popitem(last=False)
        # Keep short and cached reads synchronous within the connector's existing deadline.
        if created:
            wait((future,), timeout=wait_seconds)
        return self.reply(query_id, future, user)

    def run(self, args, user):
        try:
            return self.query(args, user)['snapshot_id'], None
        except Exception as error:
            # A failed calculation can have large, private work buffers on its stack.
            error.__context__ = error.__cause__ = None
            return None, error.with_traceback(None)

    def reply(self, query_id, future, user):
        if not future.done():
            return 202, {'status': 'pending', 'query_id': query_id, 'retryAfter': 5}
        snapshot_id, error = future.result()
        if error is not None:
            raise error.with_traceback(None)
        # Use the normal frozen-snapshot path to recheck effective scope before each delivery.
        return 200, self.query({'snapshot_id': snapshot_id}, user)
