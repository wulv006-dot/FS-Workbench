"""Run only official agent construction in an isolated home; sockets are blocked."""
import asyncio,base64,json,os,socket,sys,tempfile,types
from pathlib import Path
from unittest.mock import patch

CASE='__CASE__'
ROOT=Path('/opt/pilot')
import hermes_yaml as yaml
fs_config=(ROOT/'runtime-config.yaml').read_bytes()
desktop=yaml.safe_load(Path('/profile/config.yaml').read_text()) or {}
desktop_model={k:v for k,v in desktop.get('model',{}).items() if k in ('default','provider','base_url','context_length','streaming','reasoning_echo')}
if CASE=='desktop_changed':desktop_model['base_url']='https://desktop.example.invalid/v1'
socket_attempts=[]
def reject_socket(self,address):
    socket_attempts.append('blocked')
    raise OSError('isolated_construction_network_disabled')
socket.socket.connect=reject_socket
with tempfile.TemporaryDirectory(prefix='fs-config-isolation-') as folder:
    home=Path(folder);os.environ['HERMES_HOME']=str(home);os.environ['HOME']=str(home)
    (home/'config.yaml').write_text(json.dumps({'model':desktop_model}))
    (home/'runtime-config.yaml').write_bytes(fs_config)
    source=(ROOT/'hermes_worker.py').read_text() if CASE=='before' else base64.b64decode('__CANDIDATE_BASE64__').decode()
    module=types.ModuleType('fs_config_candidate');module.__file__=str(home/'hermes_worker.py')
    sys.modules[module.__name__]=module
    exec(compile(source,module.__file__,'exec'),module.__dict__)
    import skill_bundle
    bundle=skill_bundle.load_bundle(ROOT)
    module.admission=lambda session_id:{'ready':True,'token':'Q'*48,'model':'deepseek-flash','prompt':'Isolated construction QA only; do not run tools or model.','reasoning_effort':'high'}
    async def verify():
        adapter=module.make_adapter('isolated-api-key')
        adapter._ensure_session_db=lambda:None
        agent=None
        try:
            with patch.object(skill_bundle,'load_bundle',return_value=bundle):
                agent=adapter._create_agent(session_id='isolated-construction')
            from hermes_cli import config
            from proxy_gateway import MAX_PROVIDER_CONTEXT_TOKENS
            cfg=config.load_config()
            result={'case':CASE,'constructed':True,'context':agent.context_compressor._config_context_length,'expectedContext':MAX_PROVIDER_CONTEXT_TOKENS,'toolsExact':set(agent.valid_tool_names)==set(module.WIRE_TOOLS),'toolCount':len(agent.valid_tool_names),'toolSearchDisabled':cfg['tools']['tool_search']['enabled'] is False,'streaming':cfg['model']['streaming'],'reasoningEcho':cfg['model']['reasoning_echo'],'maxConcurrentRuns':adapter._max_concurrent_runs,'configOwnedByFS':config.get_config_path()==home/'runtime-config.yaml','skillVersion':bundle['version'],'blockedSocketAttempts':len(socket_attempts),'modelCalls':0}
            assert CASE!='before','baseline unexpectedly passed'
            assert result['context']==result['expectedContext']==1048576
            assert result['toolsExact'] and result['toolSearchDisabled'] and result['configOwnedByFS']
            assert result['streaming'] is False and result['reasoningEcho'] is True and result['maxConcurrentRuns']==0
            print('FS_CONFIG_QA='+json.dumps(result))
        except PermissionError as error:
            if CASE!='before' or str(error)!='context_window_configuration_mismatch':raise
            print('FS_CONFIG_QA='+json.dumps({'case':CASE,'reproduced':str(error),'blockedSocketAttempts':len(socket_attempts),'modelCalls':0}))
        finally:
            if agent is not None:agent.close()
    asyncio.run(verify())
    # Drain the official async logger before removing this isolated home.
    import hermes_logging,logging,logging.handlers
    for value in vars(hermes_logging).values():
        if isinstance(value,logging.handlers.QueueListener):value.stop()
    logging.shutdown()
