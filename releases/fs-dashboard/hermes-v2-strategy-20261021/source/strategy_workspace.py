"""Existing authenticated advisor entry: read research and existing action receipts."""
import json
from strategy_tools import allowed,schema,read_review
from pricing_simulation import SimulationBridge


def handle(service,user,body):
    if not service.authorizer(user):return 403,{'error':'admin_required'}
    try:
        allowed(user);action=body.get('action')
        if action=='set_enabled' and set(body)=={'kind','action','enabled'}:
            if type(body['enabled']) is not bool:raise ValueError('strategy_enabled_boolean')
            with service.tasks.db() as db:
                schema(db);db.execute('INSERT OR REPLACE INTO strategy_control VALUES(?,?)',(user,int(body['enabled'])))
            return 200,{'enabled':body['enabled'],'business_write_performed':False,'existing_automation_unchanged':True}
        if action=='read_review' and set(body)=={'kind','action','decision_id','start','end'}:
            with service.tasks.db() as db:return 200,read_review(db,user,{k:body[k] for k in ('decision_id','start','end')},service.action_history(user))
        if action!='list' or set(body)!={'kind','action'}:raise ValueError('strategy_workspace_fields')
        with service.tasks.db() as db:
            schema(db);control=db.execute('SELECT enabled FROM strategy_control WHERE owner=?',(user,)).fetchone()
            drafts=[dict(r) for r in db.execute('SELECT * FROM strategy_drafts WHERE owner=? AND project=? ORDER BY rowid DESC LIMIT 50',(user,'FC27'))]
            simulations=[dict(r) for r in db.execute('SELECT * FROM strategy_simulations WHERE owner=? ORDER BY rowid DESC LIMIT 50',(user,))]
            methods=[dict(r) for r in db.execute('SELECT * FROM method_candidates WHERE owner=? AND project=? ORDER BY rowid DESC LIMIT 50',(user,'FS'))]
        for row in drafts+simulations+methods:row['content']=json.loads(row['content'])
        try:capabilities=dict(SimulationBridge().capabilities(),status='available')
        except (OSError,ValueError,TypeError,KeyError) as error:capabilities={'status':'unavailable','reason':str(error) if isinstance(error,ValueError) else type(error).__name__}
        from report_method import HTML_DESIGN_MANIFEST_SHA256
        for row in methods:row['state']='base_conflict' if row['base_manifest']!=HTML_DESIGN_MANIFEST_SHA256 else 'needs_human_review'
        return 200,dict(contract='hermes-strategy-research-v1',owner=user,project='FC27',enabled=control is None or bool(control[0]),
            capabilities=capabilities,drafts=drafts,simulations=simulations,method_candidates=methods,
            action_history=service.action_history(user),execution_authorized=False,business_write_performed=False)
    except PermissionError as error:return 403,{'error':str(error)}
    except (ValueError,TypeError,KeyError) as error:return 409 if 'conflict' in str(error) or 'changed' in str(error) else 422,{'error':str(error) if isinstance(error,ValueError) else 'strategy_invalid_request'}
