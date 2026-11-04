"""Start the pinned official full Desktop backend on the existing Hermes home."""
import os
from pathlib import Path
import secrets
import json

home = Path(os.environ['HERMES_HOME'])
private = home / '.desktop-management'
private.mkdir(mode=0o700, exist_ok=True)
token = private / 'token'
if not token.exists():
    fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(secrets.token_urlsafe(32))
os.environ['HERMES_DASHBOARD_SESSION_TOKEN'] = token.read_text().strip()
os.environ['OPENAI_API_KEY'] = Path('/fs/secrets/deepseek.key').read_text('utf-8-sig').strip()
os.environ['OPENAI_BASE_URL'] = 'https://api.deepseek.com/v1'
os.environ['HERMES_SERVE_HEADLESS'] = '1'
config = home / 'config.yaml'
if not config.exists() or not config.read_text().strip():
    config.write_text(json.dumps({
        'model': {'default': 'deepseek-flash', 'provider': 'custom',
                  'base_url': 'https://api.deepseek.com/v1', 'api_mode': 'chat_completions',
                  'context_length': 1048576, 'streaming': True},
        'agent': {'reasoning_effort': 'high', 'max_tokens': 393216},
        'terminal': {'backend': 'local'},
    }, indent=2))

from hermes_cli.web_server import start_server
import hermes_cli.web_server as desktop_server
from desktop_fs_gateway import install_fs_desktop
install_fs_desktop(desktop_server)

start_server(host='127.0.0.1', port=8942, open_browser=False, headless=True)
