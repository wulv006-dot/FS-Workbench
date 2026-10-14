"""One-shot daily workspace refreshes; reuse the existing bounded model ledger."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
import re
from pathlib import Path
import stat
import tempfile
import time
import signal
import urllib.error
import urllib.parse
import urllib.request
import uuid

SHANGHAI = timezone(timedelta(hours=8))
SCHEDULES = {'game-monitor': (0, 5), 'management': (0, 20)}
MODULES = {'game-monitor': 'game_intelligence', 'management': 'management_daily'}
STATE_ROOT = Path('/var/lib/fs-boss-workspaces')
MODEL_ROOT = '/var/lib/fs-business-ranges/fc-daily'
NO_FACTS = {'unavailable', 'target_period_expired', 'no_complete_days'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def now():
    return datetime.now(SHANGHAI)


def checked_time(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('aware_time_required')
    return value.astimezone(SHANGHAI)


@contextmanager
def scheduled_deadline(seconds):
    if seconds is None:
        yield
        return
    if seconds <= 0:
        raise TimeoutError('nightly_deadline_exceeded')
    if not hasattr(signal,'setitimer'):
        raise RuntimeError('scheduled_deadline_requires_posix')
    def expired(*args):
        raise TimeoutError('nightly_deadline_exceeded')
    previous=signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous)


def checked_path(path):
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('linked_state_path')
        if item.exists():
            info = item.stat()
            if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                raise ValueError('invalid_state_file_type')
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise ValueError('linked_state_file')
            if os.name == 'posix' and info.st_uid != os.geteuid():
                raise ValueError('invalid_state_owner')


def sync_directory(path):
    if os.name == 'nt':
        return  # Windows offline tests cannot attest POSIX directory durability.
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data, mode):
    checked_path(path)
    fd, temporary = tempfile.mkstemp(prefix='.boss-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), mode) if hasattr(os, 'fchmod') else os.chmod(temporary, mode)
            os.fsync(handle.fileno())
        checked_path(path)
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    checked_path(path)
    return json.loads(path.read_bytes()) if path.exists() else None


@contextmanager
def file_lock(path):
    checked_path(path)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('unsafe_lock_file')
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise BlockingIOError('daily_lock_busy') from error
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_summary(path,deadline=None):
    """Only the explicitly authorized existing wulv read path on loopback."""
    parsed = urllib.parse.urlsplit(path)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != '/dashboard/fs-home/range.json' or any(len(v) != 1 for v in query.values()):
        raise ValueError('invalid_source_route')
    mode = query.get('mode', [None])[0]
    allowed = {'mode'} if mode == 'catalog' else {'mode', 'profile', 'start', 'end'}
    if mode not in ('catalog', 'summary') or set(query) != allowed:
        raise ValueError('invalid_source_query')
    if mode == 'summary':
        from datetime import date
        if not query['profile'][0].replace('_', '').isalnum() or len(query['profile'][0]) > 48:
            raise ValueError('invalid_source_profile')
        for field in ('start', 'end'):
            if date.fromisoformat(query[field][0]).isoformat() != query[field][0]:
                raise ValueError('invalid_source_date')
    request = urllib.request.Request('http://127.0.0.1:8931/range?' + parsed.query,
                                     headers={'X-Auth-User': 'wulv', 'Accept': 'application/json'})
    try:
        def read(control=None):
            handlers=(NoRedirect(),*control.handlers()) if control is not None else (NoRedirect(),)
            with urllib.request.build_opener(*handlers).open(request, timeout=min(20,control.remaining()) if control is not None else 20) as response:
                raw = response.read(2000001)
                if len(raw) > 2000000:raise ValueError('source_response_too_large')
                return {'http_status': response.status, 'body': json.loads(raw)}
        if deadline is None:return read()
        from nightly_http import Deadline
        with Deadline(deadline) as control:return control.run(lambda:read(control))
    except urllib.error.HTTPError as error:
        return {'http_status': error.code, 'body': {}}


def bounded_model(projected, callback):
    from fc_daily import DailyReports
    return DailyReports(None, MODEL_ROOT).bounded_model(projected, callback)


def request_model(messages, projected, validator, **kwargs):
    from ai_advisor_model import request_model as request
    return request(messages, projected, validator, **kwargs)


class DailyRunner:
    def __init__(self, root=STATE_ROOT, *, clock=now, modules=None, reader=read_summary,
                 model_runner=bounded_model, provider=request_model, wait=time.sleep):
        self.root, self.clock = Path(root), clock
        self.modules, self.reader = modules, reader
        self.model_runner, self.provider = model_runner, provider
        self.wait = wait
        self.deadline = None

    def check_deadline(self):
        if self.deadline is not None and checked_time(self.clock())>=self.deadline:
            raise TimeoutError('nightly_deadline_exceeded')

    def paths(self, kind, day):
        if kind not in SCHEDULES:
            raise ValueError('invalid_kind')
        return {'journal': self.root / 'journal' / kind / (day + '.json'),
                'lock': self.root / 'locks' / (kind + '-' + day + '.lock'),
                'public': self.root / 'public' / (kind + '.json'),
                'status': self.root / 'public' / (kind + '.status.json')}

    def prepare(self, kind):
        for path, mode in [(self.root, 0o755), (self.root / 'public', 0o755),
                           (self.root / 'locks', 0o700), (self.root / 'journal', 0o700),
                           (self.root / 'journal' / kind, 0o700), (self.root / 'history', 0o700),
                           (self.root / 'history' / kind, 0o700), (self.root / 'diagnostics', 0o700),
                           (self.root / 'diagnostics' / kind, 0o700)]:
            checked_path(path)
            path.mkdir(parents=True, exist_ok=True, mode=mode)
            path.chmod(mode)

    def summary(self, journal, paths):
        checked_path(paths['public'])
        current = paths['public'].read_bytes() if paths['public'].exists() else None
        result = {key: journal.get(key) for key in ('kind', 'day', 'run_id', 'trigger', 'started_at',
                'finished_at', 'status', 'phase', 'source_sha256', 'ai_status', 'fact_status', 'error_code', 'analysis_of')} | {
                'public_available': current is not None,
                'public_sha256': digest(current) if current is not None else None,
                'publication_matches_journal': bool(current and journal.get('publish_sha256') == digest(current)),
                'same_day_replay_disabled': True}
        if journal.get('phase') != 'completed':
            result['status'] = 'unknown' if journal.get('phase') == 'model_pending' else 'incomplete'
        return result

    def inspect(self, kind=None):
        at = checked_time(self.clock())
        kinds = [kind] if kind else list(SCHEDULES)
        result = {}
        for selected in kinds:
            paths = self.paths(selected, at.date().isoformat())
            journal = read_json(paths['journal'])
            result[selected] = {'schedule': '%02d:%02d Asia/Shanghai' % SCHEDULES[selected],
                                'today': self.summary(journal, paths) if journal else {'status': 'not_run'},
                                'last_status': read_json(paths['status'])}
        return {'read_only': True, 'at': at.isoformat(), 'workspaces': result}

    def run(self, kind, trigger):
        self.deadline=None
        if trigger not in ('manual', 'scheduled'):
            raise ValueError('invalid_trigger')
        at = checked_time(self.clock())
        paths = self.paths(kind, at.date().isoformat())
        hour, minute = SCHEDULES[kind]
        if trigger == 'scheduled' and (at.hour>=7 or at < at.replace(hour=hour, minute=minute, second=0, microsecond=0)):
            return {'kind': kind, 'day': at.date().isoformat(), 'status': 'not_due', 'same_day_replay_disabled': True}
        self.prepare(kind)
        try:
            with file_lock(paths['lock']):
                previous_run = read_json(paths['journal'])
                if previous_run:
                    return self.summary(previous_run, paths)
                self.deadline=at.replace(hour=6,minute=59,second=0,microsecond=0) if trigger=='scheduled' else None
                remaining=(self.deadline-at).total_seconds() if self.deadline is not None else None
                with scheduled_deadline(remaining):
                    return self.execute(kind, trigger, at, paths)
        except BlockingIOError:
            return {'kind': kind, 'day': at.date().isoformat(), 'status': 'busy', 'same_day_replay_disabled': True}

    def analyse(self, kind, after_run_id, *, recorded=False):
        self.deadline=None
        at = checked_time(self.clock())
        paths = self.paths(kind, at.date().isoformat())
        if not isinstance(after_run_id, str) or not re.fullmatch(re.escape(kind)+r'-\d{4}-\d{2}-\d{2}-[a-f0-9]{32}', after_run_id):
            raise ValueError('invalid_prior_run_id')
        if not paths['journal'].parent.is_dir():
            raise ValueError('prior_run_not_found')
        with file_lock(paths['lock']):
            priors = [read_json(p) for p in paths['journal'].parent.glob('*.json')]
            matches = [j for j in priors if j and j.get('run_id') == after_run_id]
            if len(matches) != 1:
                raise ValueError('prior_run_not_found')
            prior = matches[0]
            if (prior.get('day') != at.date().isoformat() or prior.get('phase') != 'completed' or
                    prior.get('status') not in ('model_failed', 'facts_only') or prior.get('ai_status') != 'invalid_response'):
                raise ValueError('only_completed_invalid_response_can_be_reanalysed')
            batch = prior['projected']
            if digest(encoded(batch)) != prior['source_sha256']:
                raise ValueError('prior_source_changed')
            recorded_response = None
            if recorded:
                diagnostic = self.root / 'diagnostics' / kind / (after_run_id + '.json')
                checked_path(diagnostic)
                raw = diagnostic.read_bytes()
                if len(raw) > 96000 or digest(raw) != prior.get('model_result', {}).get('response_sha256'):
                    raise ValueError('recorded_response_changed')
                recorded_response = json.loads(raw)
            action = 'revalidation' if recorded else 'analysis'
            paths['journal'] = paths['journal'].with_name(at.date().isoformat()+'-'+action+'-'+digest(after_run_id.encode())[:16]+'.json')
            existing = read_json(paths['journal'])
            if existing:
                return self.summary(existing, paths)
            self.prepare(kind)
            batch = dict(batch, manual_analysis_of=after_run_id)
            return self.execute(kind, 'manual_'+action, at, paths, batch=batch, analysis_of=after_run_id, recorded_response=recorded_response)

    def execute(self, kind, trigger, at, paths, batch=None, analysis_of=None, recorded_response=None):
        checked_path(paths['public'])
        previous_bytes = paths['public'].read_bytes() if paths['public'].exists() else None
        previous = json.loads(previous_bytes) if previous_bytes else None
        journal = {'schema_version': 1, 'kind': kind, 'day': at.date().isoformat(),
                   'run_id': kind + '-' + at.date().isoformat() + '-' + uuid.uuid4().hex,
                   'trigger': trigger, 'started_at': at.isoformat(), 'status': 'running',
                   'phase': 'collecting', 'ai_status': 'not_requested', 'analysis_of': analysis_of,
                   'recorded_response_reused': recorded_response is not None}
        save = lambda: atomic(paths['journal'], encoded(journal), 0o600)
        save()
        try:
            module = self.modules[kind] if self.modules else importlib.import_module(MODULES[kind])
            if batch is None:
                if self.deadline is None:
                    batch = module.collect(at, reader=self.reader) if kind == 'management' else module.collect(at)
                else:
                    reader=(lambda path:read_summary(path,deadline=self.deadline)) if self.reader is read_summary else self.reader
                    batch = module.collect(at, reader=reader, deadline_at=self.deadline) if kind=='management' else module.collect(at,deadline_at=self.deadline)
            journal.update(projected=batch, source_sha256=digest(encoded(batch)), phase='source_ready',
                           fact_status=batch.get('status', 'available' if batch.get('documents') else 'unavailable'))
            save()
            has_facts = journal['fact_status'] not in NO_FACTS
            if not has_facts:
                journal.update(status='source_unavailable', error_code=journal['fact_status'])
            else:
                messages = module.messages(batch)
                journal.update(phase='model_pending', ai_status='unknown')
                save()
                def validate_with_diagnostic(raw, projected):
                    response = encoded(raw)
                    if len(response) > 96000:
                        return {'status': 'invalid_response', 'error_code': 'response_too_large'}
                    diagnostic = self.root / 'diagnostics' / kind / (journal['run_id'] + '.json')
                    # Keep only this task's bounded response privately, never credentials or request headers.
                    atomic(diagnostic, response, 0o600)
                    try:
                        return module.validate_response(raw, projected)
                    except (ValueError, KeyError, IndexError, TypeError) as error:
                        code = str(error) if re.fullmatch(r'[a-z_]{1,64}', str(error)) else 'response_validation_failed'
                        receipt = raw.get('id') if isinstance(raw, dict) else None
                        return {'status': 'invalid_response', 'error_code': code,
                                'receipt': receipt if isinstance(receipt, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', receipt) else None,
                                'response_sha256': digest(response)}
                def callback(projected):
                    self.check_deadline()
                    return self.provider(messages, projected, validate_with_diagnostic,
                                         max_tokens=6000 if kind == 'game-monitor' else 5000,
                                         timeout=min(120,max(.1,(self.deadline-checked_time(self.clock())).total_seconds())) if self.deadline is not None else 120)
                try:
                    self.check_deadline()
                    result = validate_with_diagnostic(recorded_response, batch) if recorded_response is not None else self.model_runner(batch, callback)
                    if type(result) is dict and result.get('status') == 'model_busy' and not result.get('receipt'):
                        # The shared ledger explicitly confirms no provider request was sent.
                        journal.update(phase='model_waiting', ai_status='model_busy', busy_retry=1)
                        save()
                        self.wait(20)
                        journal.update(phase='model_pending', ai_status='unknown')
                        save()
                        result = self.model_runner(batch, callback)
                    if type(result) is not dict or not isinstance(result.get('status'), str):
                        result = {'status': 'invalid_response'}
                except Exception:
                    result = {'status': 'unknown_model_error'}
                self.check_deadline()
                journal.update(model_result=result, ai_status=result['status'], phase='model_finished')
                save()
                if kind == 'game-monitor' and result['status'] != 'succeeded':
                    journal['status'] = 'model_failed'
                else:
                    snapshot = module.build_snapshot(batch, result, previous)
                    data = encoded(snapshot)
                    final_status = 'succeeded' if result['status'] == 'succeeded' else 'facts_only'
                    journal.update(phase='publish_pending', publish_sha256=digest(data), status='publishing')
                    save()
                    history = self.root / 'history' / kind / (journal['run_id'] + '.json')
                    atomic(history, data, 0o600)
                    checked_path(paths['public'])
                    current = paths['public'].read_bytes() if paths['public'].exists() else None
                    if current != previous_bytes:
                        raise ValueError('public_changed')
                    self.check_deadline()
                    atomic(paths['public'], data, 0o644)
                    journal['status'] = final_status
        except TimeoutError:
            journal.update(status='failed',error_code='nightly_deadline_exceeded')
        except Exception:
            journal.update(status='failed', error_code='source_or_publication_failed')
        journal.update(phase='completed', finished_at=checked_time(self.clock()).isoformat())
        save()
        status = self.summary(journal, paths)
        atomic(paths['status'], encoded(status), 0o644)
        return status


def main():
    parser = argparse.ArgumentParser(description='Inspect without writes; run once per workspace per Shanghai day.')
    sub = parser.add_subparsers(dest='action', required=True)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('--kind', choices=SCHEDULES)
    run = sub.add_parser('run', help='Creates a daily journal and may call the paid model; same-day repeats only read back.')
    run.add_argument('--kind', choices=SCHEDULES, required=True)
    run.add_argument('--trigger', choices=('manual', 'scheduled'), required=True)
    analysis = sub.add_parser('analyse', help='Explicit new manual analysis after a completed invalid response; preserves the original run.')
    analysis.add_argument('--kind', choices=SCHEDULES, required=True)
    analysis.add_argument('--after-run-id', required=True)
    analysis.add_argument('--recorded-response', action='store_true', help='Revalidate a SHA-pinned saved response without any model request.')
    args = parser.parse_args()
    runner = DailyRunner()
    result = (runner.inspect(args.kind) if args.action == 'inspect' else
              runner.analyse(args.kind, args.after_run_id, recorded=args.recorded_response) if args.action == 'analyse' else runner.run(args.kind, args.trigger))
    print(encoded(result).decode('utf-8'))
    if args.action != 'inspect' and result.get('status') not in ('succeeded', 'not_due'):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
