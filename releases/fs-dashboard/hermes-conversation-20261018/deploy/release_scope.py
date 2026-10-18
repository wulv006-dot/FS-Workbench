"""The only production paths this release may change."""

SCOPE = "fs-hermes-conversation-20261018-v1"
TARGETS = {
    "source/conversation_store.py": "/opt/fs-hermes-fc/conversation_store.py",
    "source/conversation_service.py": "/opt/fs-hermes-fc/conversation_service.py",
    "source/hermes_worker.py": "/opt/fs-hermes-fc/hermes_worker.py",
    "source/fs_evidence.py": "/opt/fs-hermes-fc/fs_evidence.py",
    "source/conversation_http.py": "/opt/fs-exact-range-20261001/conversation_http.py",
    "source/http/range_api.py": "/opt/fs-exact-range-20261001/range_api.py",
    "source/http/formal.conf": "/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf",
    "frontend/index.html": "/var/www/dashboard/fs-home/hermes/conversation/index.html",
    "frontend/conversation.css": "/var/www/dashboard/fs-home/hermes/conversation/conversation.css",
    "frontend/conversation.js": "/var/www/dashboard/fs-home/hermes/conversation/conversation.js",
    "frontend/entry/brain.js": "/var/www/dashboard/fs-home/brain/brain.js",
    "source/worker-install-state-isolation.conf": "/etc/systemd/system/fs-hermes-fc.service.d/install-state-isolation.conf",
}
NEW_ALLOWED = {
    "/opt/fs-hermes-fc/conversation_store.py",
    "/opt/fs-hermes-fc/conversation_service.py",
    "/opt/fs-exact-range-20261001/conversation_http.py",
    "/var/www/dashboard/fs-home/hermes/conversation/index.html",
    "/var/www/dashboard/fs-home/hermes/conversation/conversation.css",
    "/var/www/dashboard/fs-home/hermes/conversation/conversation.js",
}
