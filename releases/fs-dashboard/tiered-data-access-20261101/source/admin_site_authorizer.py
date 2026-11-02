"""Narrow owner-injected permission adapter: configured site 266 + platform admin only.

Host supplies trusted identity and read-existing-only loaders for current IAM
policy and service config. This never creates or writes policy, reads secrets, or
establishes an Admin session. Any missing or ambiguous dependency fails closed.
"""
import hashlib,json

def digest(value):
 return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()

class ConfiguredAdminAuthorizer:
 def __init__(self,*,subject,load_policy,load_config,rbac,policy_version):
  if not isinstance(subject,str) or not subject or not isinstance(policy_version,str) or not policy_version or not callable(load_policy) or not callable(load_config):raise ValueError('trusted_host_inputs_required')
  self.subject,self.load_policy,self.load_config,self.rbac,self.policy_version=subject,load_policy,load_config,rbac,policy_version
 def __call__(self,query):
  if not isinstance(query,dict) or query.get('site_id')!='266' or not isinstance(query.get('game_id'),str) or not query['game_id'].isascii() or not query['game_id'].isdigit():return None
  try:
   policy=self.rbac.validate(self.load_policy());config=self.load_config()
   if not isinstance(policy,dict) or not isinstance(config,dict) or config.get('activation_status')!='W0_verified':return None
   sites=config.get('sites');projects=config.get('projects')
   if not isinstance(sites,dict) or set(sites)!={'266'} or not isinstance(projects,dict) or query['game_id'] not in projects:return None
   if self.rbac.authorize(policy,self.subject,'GET','/dashboard/users/')!=200 or self.rbac.is_admin(policy,self.subject) is not True:return None
   return dict(scope_hash=digest([self.subject,'266',query['game_id']]),permission_epoch=digest([policy,config]),policy_version=self.policy_version)
  except (OSError,ValueError,TypeError,KeyError,AttributeError):return None
