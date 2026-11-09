"""Read the original subject's published knowledge route behind existing FS permissions."""
import hashlib
import json
import re

from .catalog import ValidationError, permit


class KnowledgeUnavailable(RuntimeError):
    status_code = 503

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class KnowledgeService:
    def __init__(self, root, catalog, authorize, *, redact=None):
        # All dependencies and filesystem roots are service configuration, never tool arguments.
        self.root, self.catalog, self.authorize = root, catalog, authorize
        self.redact = redact

    def _selection(self, principal):
        permit(self.authorize, principal, '/dashboard/fs-home/brain/', 'GET')
        try:
            selected = self.catalog.task_selection(self.root, owner=principal.subject,
                        project='FS', channel='fs', task_type='data')
        except (ValueError, OSError):
            raise KnowledgeUnavailable('knowledge_source_unavailable') from None
        if selected is None:
            raise KnowledgeUnavailable('knowledge_route_unavailable')
        self.catalog.verify_selection(selected)
        if selected.get('status') != 'available' or selected.get('history'):
            raise KnowledgeUnavailable('published_knowledge_required')
        return selected

    @staticmethod
    def _metadata(selected):
        return {key: selected[key] for key in ('release', 'catalog_sha256', 'source_commit')}

    def index(self, principal, *, history=False):
        if type(history) is not bool:
            raise ValidationError('invalid_knowledge_query')
        selected = self._selection(principal)
        candidates = selected['entries']
        if history:
            try:
                raw = self.catalog.read_bound(self.root, selected['catalog'])
                if hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != selected['catalog_sha256']:
                    raise ValueError('knowledge_catalog_changed')
                index = self.catalog.validate(json.loads(raw))
                permitted = set(selected.get('history_entry_ids', ()))
                candidates = [*candidates, *(row for row in index['entries'] if row['id'] in permitted
                    and row['layer'] == 'archive' and set(row['modules']) & set(selected['modules']))]
            except (ValueError, OSError):
                raise KnowledgeUnavailable('knowledge_source_unavailable') from None
        entries = []
        for entry in candidates:
            entries.append({key: entry[key] for key in
                ('id', 'revision', 'layer', 'status', 'modules', 'effective_at', 'source_commit') if key in entry})
        permit(self.authorize, principal, '/dashboard/fs-home/brain/', 'GET')
        return dict(self._metadata(selected), status='index_only', history=history, entries=entries, complete=True)

    def read(self, principal, entry_id, *, revision=None, history=False):
        if (not isinstance(entry_id, str) or re.fullmatch(r'[a-z0-9][a-z0-9_.-]{1,100}', entry_id) is None
                or type(history) is not bool or revision is not None and
                (not isinstance(revision, str) or not 1 <= len(revision) <= 160)):
            raise ValidationError('invalid_knowledge_query')
        if revision is not None and not history:
            raise ValidationError('historical_version_requires_explicit_history')
        selected = self._selection(principal)
        if history:
            if entry_id not in selected.get('history_entry_ids', ()):
                raise PermissionError('knowledge_history_scope_denied')
            try:
                value = self.catalog.select(self.root, selected['catalog'], selected['catalog_sha256'],
                            selected['modules'], [entry_id], revision, history=True)
            except (ValueError, OSError):
                raise KnowledgeUnavailable('knowledge_source_unavailable') from None
            if value.get('status') != 'available' or len(value['entries']) != 1:
                raise KnowledgeUnavailable('knowledge_history_unavailable')
            entry = value['entries'][0]
        else:
            entry = next((row for row in selected['entries'] if row['id'] == entry_id), None)
            if entry is None:
                raise PermissionError('knowledge_entry_scope_denied')
        if self.redact is None:
            raise KnowledgeUnavailable('knowledge_content_projection_unavailable')
        original = entry['content']
        content = self.redact(original)
        if not isinstance(content, str) or len(content.encode('utf-8')) > 1048576:
            raise KnowledgeUnavailable('knowledge_content_boundary')
        # Recheck original portal grants after loading and before returning the content.
        permit(self.authorize, principal, '/dashboard/fs-home/brain/', 'GET')
        return dict(self._metadata(selected), status='available', history=history,
                    entry={key: entry[key] for key in ('id', 'revision', 'layer', 'status', 'modules', 'effective_at')},
                    content=content, source_content_sha256=entry['content_sha256'],
                    content_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest(),
                    redacted=content != original)
