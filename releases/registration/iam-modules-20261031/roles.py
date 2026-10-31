"""Module role migration; preserve explicit denies and previous individual rights."""
import copy

def migrate(old, rbac):
    p=copy.deepcopy(old)
    specs=[('SportsOps','球类运营','sports'),('ArpgOps','RPG 运营','arpg'),
           ('MarketingOps','营销运营','marketing'),('ActivityOps','活动运营','activities'),
           ('AnalyticsOps','数据运营','analytics'),('BrainOps','智体运营','brain'),
           ('BotsOps','机器人运营','bots'),('CollabOps','协作运营','collaboration')]
    roles={k:copy.deepcopy(old['roles'][k]) for k in ('PlatformAdmin','Viewer','Deployer','FCObserver') if k in old['roles']}
    for key,label,section in specs:
        roles[key]={'label':label,'desc':'负责'+dict(rbac.SECTIONS)[section]+'；不含平台管理或部署',
                    'rules':[{'resources':[rid for rid,_,sec,_ in rbac.RESOURCES if sec==section],
                              'actions':['view','edit','execute']},
                             {'resources':['home','identity'],'actions':['view']}]}
    p['roles']=roles
    for subject,b in p['bindings'].items():
        if 'PlatformAdmin' in b.get('roles',[]): continue
        if subject=='dot_fc_observer':
            b['roles']=['FCObserver']; continue
        prior=rbac.grant_matrix(old,subject)
        bound=[r for r in b.get('roles',[]) if r in ('Viewer','Deployer','FCObserver')]
        if any(r in b.get('roles',[]) for r in ('Auditor','CollabEditor')) and 'Viewer' not in bound: bound.append('Viewer')
        for key,label,sec in specs:
            resources=roles[key]['rules'][0]['resources']
            # Sports/ARPG already named by administrators retain their module assignment.
            if key in b.get('roles',[]) or all(set(['view','edit','execute'])<=set(prior.get(r,[])) for r in resources):
                bound.append(key)
        b['roles']=sorted(set(bound)); b['grants']=[]
        current=rbac.grant_matrix(p,subject)
        groups={}
        for rid,actions in prior.items():
            extra=tuple(sorted(set(actions)-set(current.get(rid,[]))))
            if extra:groups.setdefault(extra,[]).append(rid)
        b['grants']=[{'resources':sorted(rs),'actions':list(a)} for a,rs in groups.items()]
        if not b['grants']:b.pop('grants',None)
    rbac.validate(p)
    return p
