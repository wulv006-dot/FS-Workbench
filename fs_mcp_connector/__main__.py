"""Run the separately deployed FS connector; configuration never supplies a user identity."""
import hmac
import importlib.util
import logging
import os
from pathlib import Path

import uvicorn

from .auth import AuthStore
from .backend import Backend
from .catalog import Catalog
from .portal import Portal, PortalError
from .server import create_app
from .knowledge import KnowledgeService
from .players import PlayersService


def app_from_environment():
    logging.getLogger('httpx').setLevel(logging.WARNING)
    issuer = os.environ['FS_CONNECTOR_ISSUER'].rstrip('/')
    resource = issuer + '/mcp'
    portal = Portal(os.environ.get('FS_CONNECTOR_PORTAL', 'http://127.0.0.1:8895'))

    def authorize(principal, path, method):
        try:
            current = portal.verify(principal.session_cookie, path, method)
        except PortalError as error:
            return error.status
        return hmac.compare_digest(current.subject, principal.subject)

    store = AuthStore(Path(os.environ['FS_CONNECTOR_DATABASE']), resource, portal)
    catalog = Catalog(authorize)
    knowledge = None
    if os.environ.get('FS_CONNECTOR_KNOWLEDGE_ROOT'):
        source = Path(__file__).resolve().parents[1] / 'releases/fs-dashboard/knowledge-layering-20261023/source/knowledge_catalog.py'
        spec = importlib.util.spec_from_file_location('fs_connector_published_knowledge', source)
        selector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(selector)
        from .redaction import redact
        knowledge = KnowledgeService(Path(os.environ['FS_CONNECTOR_KNOWLEDGE_ROOT']), selector, authorize, redact=redact)
    backend = Backend(catalog, os.environ['FS_CONNECTOR_ORIGIN'], knowledge=knowledge,
                      players=PlayersService(os.environ['FS_CONNECTOR_ORIGIN'], authorize))
    return create_app(store=store, portal=portal, catalog=catalog, backend=backend,
                      issuer=issuer, resource_url=resource)


if __name__ == '__main__':
    uvicorn.run(app_from_environment(), host='127.0.0.1',
                port=int(os.environ['FS_CONNECTOR_PORT']), access_log=False)
