"""Ephemeral Order-reader process domain; existing browser/session, no login."""
import json
from pathlib import Path
import re
import subprocess
import uuid

SOCKET = Path('/run/fs-order-session/session.sock')
CLIENT = Path('/opt/fs-order-session/fs_order_client.py')
CONTAINER = 'fs-order-browser'
ENDPOINT_ALIAS = b'http://127.0.0.1:9226'
ENDPOINT = b'http://127.0.0.1:9225'


def cleanup(name):
    if not re.fullmatch(r'fs-transaction-reader-[a-f0-9]{32}',name):
        raise ValueError('owned_reader_container_required')
    try:
        result=subprocess.run(['docker','rm','--force',name],capture_output=True,text=True,timeout=10)
        if result.returncode==0:
            return
        check=subprocess.run(['docker','inspect',name],capture_output=True,text=True,timeout=5)
        if check.returncode!=0 and any(message+name in check.stderr for message in ('No such object: ','No such container: ')):
            return
    except (OSError,subprocess.TimeoutExpired) as error:
        raise RuntimeError('order_reader_cleanup_unverified') from error
    raise RuntimeError('order_reader_cleanup_unverified')


def run(program, requests, timeout):
    if type(timeout) is not int or not 1 <= timeout <= 900:
        raise ValueError('original_order_reader_budget_required')
    if program.count(ENDPOINT_ALIAS) != 1:
        raise ValueError('one_order_cdp_endpoint_required')
    if not SOCKET.is_socket() or not CLIENT.is_file():
        raise RuntimeError('original_order_session_resources_required')
    state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .}}',CONTAINER],text=True,timeout=5))
    if not state['State']['Running'] or state['State'].get('Restarting'):
        raise RuntimeError('order_browser_not_running')
    if not re.fullmatch(r'[a-f0-9]{64}',state['Id']) or not re.fullmatch(r'sha256:[a-f0-9]{64}',state['Image']):
        raise ValueError('order_container_identity_required')
    name='fs-transaction-reader-'+uuid.uuid4().hex
    command=['docker','run','--rm','-i','--init','--name',name,
             '--network','container:'+state['Id'],'--user','11027:11027',
             '--memory','1g','--read-only','--tmpfs','/tmp:rw,nosuid,size=128m',
             '--cap-drop','ALL','--security-opt','no-new-privileges',
             '--mount','type=bind,src='+CLIENT.as_posix()+',dst='+CLIENT.as_posix()+',readonly',
             '--mount','type=bind,src='+SOCKET.as_posix()+',dst='+SOCKET.as_posix()+',readonly',
             '--entrypoint','timeout',state['Image'],'--signal=TERM','--kill-after=1s',str(timeout)+'s',
             'python3','-B','-',json.dumps(requests)]
    try:
        return subprocess.run(command,input=program.replace(ENDPOINT_ALIAS,ENDPOINT),
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    finally:
        # The Docker CLI timeout alone does not terminate a container-side process.
        # The generated name identifies only this ephemeral runner; Chrome is never removed.
        cleanup(name)
