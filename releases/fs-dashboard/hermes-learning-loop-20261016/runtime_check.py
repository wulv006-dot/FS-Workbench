"""Same pinned Hermes construction and wire builder, isolated home, zero networking."""
import os,tempfile,json,hashlib,socket,sys,shutil
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
temp=Path(tempfile.mkdtemp(prefix='learning-runtime-'))
profile=temp/'profile';profile.mkdir()
os.environ.update(HOME=str(profile),HERMES_HOME=str(profile),HERMES_REDACT_SECRETS='true')
sys.path[:0]=[str(HERE/'source'),'/opt/pilot']
from business_context import freeze_learning
from skill_bundle import load_bundle
fs=temp/'fs';fs.mkdir();shutil.copyfile('/qa-input/desktop-business-context.md',fs/'desktop-business-context.md')
shutil.copytree('/qa-input/memories',profile/'memories')
skills=load_bundle(Path('/opt/pilot'),question='FC27经营日报',mode='daily')
knowledge=freeze_learning(fs,skills,{},'daily',skill_root=Path('/qa-input/skills'),profile_root=profile)
if Path('/qa-input/knowledge.json').exists():knowledge=json.loads(Path('/qa-input/knowledge.json').read_text('utf8'));skills=knowledge['skills']
import hermes_worker as worker
session='fc_'+'a'*64
item={'session_id':session,'token':'x'*48,'model':'deepseek-flash','ready':True,'reasoning_effort':'high',
      'prompt':'依据已加载方法分析FC27经营。','skill_question':'FC27经营日报','report_mode':'daily',
      'frozen_skills':skills,'learning_text':knowledge['text'],
      'learning_receipt':{k:knowledge[k] for k in ('version','identity','files','memory_path','native_skip_reason')}}
worker.admission=lambda sid:item
# make_adapter chooses its adjacent config: copy stays in the staging directory only.
adapter=worker.make_adapter('q'*48)
with patch.object(socket.socket,'connect',side_effect=AssertionError('network_forbidden')):
 agent=adapter._create_agent(session_id=session)
 receipt=worker.loaded_context_metadata(agent)
 assert receipt['fs_effective_input']['knowledge_present'] is True
 wire=receipt['fs_effective_input']
 from agent.system_prompt import build_system_prompt
 from agent.turn_context import build_api_messages
 from business_context import effective_learning
 agent._current_turn_timestamp=None  # QA only: the real turn prologue sets this before wire assembly.
 messages,effective=build_api_messages(agent,[],current_turn_user_idx=None,ext_prefetch_cache=None,plugin_user_context=None,moa_config=None,active_system_prompt=build_system_prompt(agent))
 assert effective_learning(knowledge,messages)['knowledge_sha256']==wire['knowledge_sha256']
 agent.close()
 from run_agent import AIAgent
 from agent.system_prompt import build_system_prompt
 from agent.turn_context import build_api_messages
 native=AIAgent(base_url=worker.PROXY+'/v1',api_key='x'*48,provider='custom',api_mode='chat_completions',model='deepseek-flash',
       enabled_toolsets=['fs_fc_readonly'],session_id='native_learning_qa',skip_memory=False,skip_context_files=True,
       load_soul_identity=False,skip_background_review=True,checkpoints_enabled=False,quiet_mode=True)
 system=build_system_prompt(native)
 memories=(profile/'memories/MEMORY.md').read_text('utf8').split('§')[0].strip()
 assert memories and memories in system,'native_memory_not_in_actual_prompt'
 assert set(native.valid_tool_names)==set(worker.WIRE_TOOLS),'native_toolset_changed'
 assert native._memory_manager is None,'unexpected_external_memory_provider'
 native_result={'skip_memory':False,'native_rule_in_actual_system_prompt':True,'toolset_unchanged':True,'external_memory_provider':False}
 native.close()
print(json.dumps({'explicit_snapshot':wire,'native_isolated_comparison':native_result,'provider_calls':0,'network_calls':0,
                  'knowledge_files':len(knowledge['files']),'home_isolated':str(profile).startswith('/tmp/'),'live_profile_written':False}))
