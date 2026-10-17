"""Existing monitor outbox -> the user's existing DingTalk bot; no new service."""
import base64, hashlib, hmac, json, re, stat, time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, parse_qs, urlencode
from urllib.request import Request, build_opener
from delivery import NoRedirect
from collector import atomic


def load_bot(path):
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o077 or meta.st_size > 8192:
        raise ValueError('private_bot_config_required')
    config = json.loads(path.read_text())
    if (set(config) != {'approved','group','activated_at','webhook','secret'}
            or config['approved'] is not True or config['group'] != '服务器及Github报警'):
        raise ValueError('bot_scope_invalid')
    url = urlsplit(config['webhook'])
    query = parse_qs(url.query)
    if (url.scheme != 'https' or url.netloc != 'oapi.dingtalk.com' or url.path != '/robot/send'
            or url.fragment or set(query) != {'access_token'} or len(query['access_token']) != 1
            or not re.fullmatch(r'[a-fA-F0-9]{64}', query['access_token'][0])):
        raise ValueError('bot_endpoint_invalid')
    activated = datetime.fromisoformat(config['activated_at'])
    if activated.utcoffset() is None or activated > datetime.now(timezone.utc):
        raise ValueError('bot_activation_invalid')
    if not isinstance(config['secret'], str):raise ValueError('bot_secret_invalid')
    return config


ISSUE_TEXT = {
    'historical_prewrite_failure':'历史自动改价任务因写价前保护拒绝而失败，已确认该任务未提交写价；新采集和依赖检查通过，按两次健康观察后再运行新一轮，失败记录保留。',
    'latest_coin_job_failed':'最近一次 FC 金币自动改价任务失败，未完成正常更新。',
    'latest_attempt_or_monitor_run_unverified':'最新采集任务状态或数据编号未对齐，尚未确认数据可用于报价。',
    'gallery_automation_disabled':'FC 球员图鉴自动化当前关闭；若是主动关闭，无需处理。',
    'coin_automation_disabled_or_manual':'FC 金币自动改价当前关闭或处于手动模式；若是主动设置，无需处理。',
    'https_or_anonymous_gate_unverified':'网站安全连接或未登录访问保护检查未通过。',
    'api_unhealthy_or_unknown':'FC 接口服务异常，或暂时无法确认状态。',
    'worker_unhealthy_or_unknown':'FC 任务执行服务异常，或暂时无法确认状态。',
    'browser_unhealthy_or_unknown':'服务器采集浏览器异常，或暂时无法确认状态。',
    'p2pah_session_unhealthy_or_unknown':'P2PAH 登录状态异常，或暂时无法确认登录有效。',
    'automation_timer_inactive_or_unknown':'自动改价定时任务未正常运行，或暂时无法确认状态。',
    'certificate_expiry_or_renewal_unhealthy':'网站安全证书临近到期，或续期检查未通过。',
    'coin_execution_needs_reconcile':'有改价操作结果尚未核实，必须按原操作编号核对。',
    'source_coverage_unverified':'报价所需的竞品、成本或汇率数据不完整，尚未通过来源检查。',
    'collection_stale_or_clock_invalid':'报价数据已超时，或采集时间异常。',
    'collection_time_unverified':'无法确认报价数据的采集时间。',
    'three_platform_publication_unverified':'PS、Xbox、PC 售价尚未全部通过核对，不能确认售卖风险已解除。',
    'published_price_unverified':'售价核对未通过，不能确认售卖风险已解除。',
    'player_switch_unknown':'无法确认球员联动任务的启用状态。',
    'player_pending_enabled':'已启用的球员联动任务存在失败或待核对记录。',
    'player_disabled_pending_retained':'球员联动已关闭，历史待核对记录仍保留；不要强行开启。',
    'gallery_task_unconfirmed':'FC 球员图鉴任务结果尚未确认，需要核对原任务。',
    'gallery_switch_unknown':'无法确认 FC 球员图鉴自动化的启用状态。',
    'gallery_automation_paused':'FC 球员图鉴自动化已暂停，需要先核对暂停原因。',
    'gallery_readback_stale_or_clock_invalid':'FC 球员图鉴检查结果已超时，或检查时间异常。',
    'gallery_readback_time_unverified':'无法确认 FC 球员图鉴的最近检查时间。',
    'queue_depth_at_least_five':'已有至少 5 个任务排队，请检查是否积压。',
    'disk_below_ten_gb':'服务器剩余磁盘空间不足 10 GB，请检查空间占用。',
    'latest_coin_all_proof_unverified':'最近一次金币改价的三平台执行记录尚未全部确认。',
    'player_dispatch_unverified':'金币改价后的球员联动任务是否已下发，尚未确认。',
    'linked_player_not_confirmed':'关联球员任务尚未确认完成。',
    'linked_player_request_proof_unverified':'关联球员请求与原金币操作记录尚未核对一致。',
    'latest_gallery_job_failed':'最近一次 FC 球员图鉴任务失败。',
    'collection_unavailable':'本次巡检未能取得业务状态，无法判断当前是否正常。',
    'business_snapshot_stale':'经营看板数据已超时，请注意页面数据的时间。',
    'business_snapshot_build_failed':'经营看板最新数据生成失败，需要检查采集与快照任务。',
    'business_snapshot_unverified':'经营看板数据完整性尚未通过检查。',
    'exact_range_health_unavailable':'经营看板的准确区间查询服务检查未通过。',
    'original_operation_state_unavailable':'无法读取原改价操作状态，不能安全判断是否需要处理。',
    'coin_job_deadline_exceeded':'FC 金币改价任务运行时间过长，需要核对原任务，不能直接重跑。',
    'coin_job_start_unverified':'无法确认 FC 金币改价任务的开始时间。',
    'rpg_state_unavailable':'RPG 改价状态接口未能读取，暂时无法确认业务是否正常。',
}
SERVICE_TEXT = {
    'fc27-cloud-api.service':'FC 接口', 'fc27-cloud-worker.service':'FC 任务执行',
    'fc27-gate.service':'FC 登录保护', 'coin_api_http_gate':'金币接口访问保护',
    'gallery_api_http_gate':'球员图鉴接口访问保护', 'fc27-gallery.service':'FC 球员图鉴',
    'fc27-player-tool.service':'球员维护工具', 'fs-business-range.service':'经营准确区间查询',
    'cloudmonitor.service':'服务器云监控',
}


def format_message(event):
    issues = [x for x in event['issues'] if re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', x['code'])][:24]
    codes = {x['code'] for x in issues}
    recovering = event['kind'] == 'recovery'
    cycle = event.get('cycle_recovery') or {}
    cycle_platforms = [p for p in cycle.get('platforms',[]) if p in {'PS','XBOX','PC'}]
    cycle_confirmed = recovering and cycle_platforms and cycle.get('result') in {'confirmed','no_price_change'}
    title = ('本次巡检恢复正常' if event['status'] == 'healthy' else '异常有所缓解，仍有提醒') if recovering else {
        'critical':'发现异常，需要处理', 'warning':'有状态提醒', 'unverified':'当前状态待核实',
        'healthy':'本次检查正常'}.get(event['status'], '当前状态待核实')
    if cycle_confirmed:title = 'FC 新自然周期已完成，其他提醒仍保留'
    demo_title = 'RPG中文消息演练' if any(code.startswith('rpg_') for code in codes) else '中文消息演练'
    lines = ['FS服务器巡检【'+(demo_title if event.get('synthetic') else title)+'】']
    try:
        stamp = datetime.fromisoformat(event['created_at'].replace('Z', '+00:00'))
        if stamp.utcoffset() is None:raise ValueError('timezone_required')
        lines.append('北京时间：'+stamp.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S'))
    except (ValueError, TypeError, AttributeError):
        lines.append('检查时间：尚未确认')
    if event.get('synthetic'):lines.append('这是通知文案演练，不代表发生新的故障或业务已恢复。')
    if cycle_confirmed:
        result = '已确认改价结果' if cycle['result'] == 'confirmed' else '本轮无需改价'
        lines.append('FC 恢复验证：'+ '、'.join(cycle_platforms)+' 已完成恢复后的新自然周期，'+result+'。')
    recovered = [s for s in event.get('recovered_sources',[]) if s in {'IGGM','U4GM','U7Buy'}]
    if recovering and recovered:
        lines.append('来源恢复：'+ '、'.join(recovered)+' 已在新一轮采集恢复有效数据，重新纳入参考；其他提醒仍按下文处理。')
    information = {'gallery_automation_disabled','coin_automation_disabled_or_manual','player_disabled_pending_retained'}
    for heading, rows in [('检查发现', [x for x in issues if x['code'] not in information]),
                          ('状态说明（不代表新的系统故障）', [x for x in issues if x['code'] in information])]:
        if rows:lines.append(heading+'：')
        for item in sorted(rows, key=lambda x: x['level'] != 'critical'):
            code = item['code']
            description = ISSUE_TEXT.get(code, '发现未识别的巡检异常，请按排查编号查看详情。')
            if code.startswith('service_unavailable:'):
                description = SERVICE_TEXT.get(code.split(':',1)[1], '一项依赖')+'服务或访问检查未通过，暂时无法确认正常。'
            elif code.startswith('rpg_dependency_unavailable:'):
                description = {'d4follow.service':'RPG 共享改价服务',
                               'p2pah-srv-exec.service':'RPG 后台任务执行服务'}.get(code.split(':',1)[1], 'RPG 依赖服务')+'检查未通过，暂时无法确认正常。'
            elif code.startswith('rpg_task_failed:'):
                parts = code.split(':')
                if len(parts)==4 and re.fullmatch(r'[0-9a-f]{12}',parts[3]):
                    scope = {'d4':'D4','poe2':'PoE2','aion2':'Aion2','shared':'RPG 共享（具体游戏待核对）'}.get(parts[1], 'RPG 共享（具体游戏待核对）')
                    kind = {'collect':'采集与改价','cost':'成本采集','our':'售价采集','apply':'改价执行'}.get(parts[2], '业务')
                    description = scope+'的'+kind+'任务失败。原任务编号：'+parts[3]+'。'
            if code.startswith('noncore_source_unavailable:') and code.split(':',1)[1] in {'IGGM','U4GM','U7Buy'}:
                description = code.split(':',1)[1]+' 本轮采集异常，暂未参与报价；Lootbar 和可用参考源通过来源检查。'
            lines.append('• '+description)
    if any(code.startswith('noncore_source_unavailable:') for code in codes):
        references = event.get('reference_sources') or {}
        for platform in ('PS','XBOX','PC'):
            available = [s for s in references.get(platform,[]) if s in {'IGGM','U4GM','U7Buy'}]
            if available:lines.append(platform+' 当前参考：'+ '、'.join(available)+'（核心 Lootbar 保留）。')
        lines.append('应急策略：仅非核心源缺失不暂停自动化，后续仍按原计划重采；如有其他异常，仍按原保护处理。')
    if any(code.startswith('rpg_') for code in codes):
        lines.append('RPG 影响：相关数据更新或改价可能受影响；此告警不能确认现有售价安全，也不表示已暂停写价。')
        lines.append('RPG 处理建议：先核对原任务和回执，不清锁、不重放；正常游戏保持原运行方式。')
    if codes & {'latest_coin_job_failed','source_coverage_unverified','collection_stale_or_clock_invalid',
                'latest_coin_all_proof_unverified','coin_job_deadline_exceeded','coin_execution_needs_reconcile'}:
        lines.append('影响：FC 自动改价存在阻塞或不确定；现有售价是否安全，需要另行核对。')
        lines.append('处理建议：先查原任务和数据来源，确认后按原流程恢复，不要强制改价或重复提交。')
    elif issues and codes - information:
        lines.append('处理建议：按上述异常核对受影响模块；主动关闭的任务无需开启。')
    if any('publication' in code or 'published_price' in code for code in codes):
        lines.append('售卖提醒：仅暂停自动写价不能证明已经止损，需要另外核对现有售价及售卖保护。')
    if cycle_confirmed:
        lines.append('此消息仅确认上述平台的新周期结果，不代表所有来源或其他模块已恢复，也不单独证明售卖保护有效。')
    elif recovering:lines.append('此消息仅表示巡检状态改善，不代表自动改价或售卖保护已恢复。')
    for operation in event.get('operation_ids', [])[:24]:
        if re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', operation):
            lines.append('原操作编号：'+operation)
    if event.get('operation_ids'):lines.append('未知操作必须按原编号核对，不清锁、不重放、不修改账本。')
    identity = event['event_id']
    lines.append('排查编号：'+(identity if re.fullmatch(r'[0-9a-f]{64}', identity) else '尚未确认'))
    return '\n'.join(lines)


def send_bot(config, event):
    # Official signing contract; don't try altered keys or repeated signature variants.
    url = config['webhook']
    if config['secret']:
        stamp = str(int(time.time()*1000))
        raw = (stamp+'\n'+config['secret']).encode()
        sign = base64.b64encode(hmac.new(config['secret'].encode(),raw,hashlib.sha256).digest()).decode()
        url += '&'+urlencode({'timestamp':stamp,'sign':sign})
    content = format_message(event)
    body = json.dumps({'msgtype':'text','text':{'content':content}},ensure_ascii=False).encode()
    request = Request(url, data=body, headers={'Content-Type':'application/json'},method='POST')
    with build_opener(NoRedirect).open(request, timeout=8) as response:
        data = json.loads(response.read(8192))
    if type(data.get('errcode')) is not int or data['errcode'] != 0:
        raise ValueError('bot_not_accepted')


def deliver_bot(directory, path, transport=send_bot, loader=load_bot):
    result = {'state':'not_configured','accepted_event_ids':[],'delivered':False}
    if not path.exists():return result
    try:
        config = loader(path)
        pending = []
        for target in (directory/'outbox').glob('*.json'):
            event = json.loads(target.read_text())
            if event.get('delivery_state') != 'pending':continue
            if datetime.fromisoformat(event['created_at']) < datetime.fromisoformat(config['activated_at']):
                event['delivery_state'] = 'retained_pre_activation';atomic(target,event);continue
            pending.append((target,event))
        pending.sort(key=lambda row:row[1]['created_at'])
        # ponytail: two transitions per five-minute tick; reuse existing bounded outbox.
        for target,event in pending[:2]:
            event['attempt_count'] += 1;atomic(target,event)
            transport(config,event)
            event.update(delivery_state='accepted',acknowledged_at=datetime.now(timezone.utc).isoformat(),
                         provider_receipt={'provider':'dingtalk','accepted':True,'delivered':False})
            atomic(target,event);result['accepted_event_ids'].append(event['event_id'])
        result['state'] = 'accepted' if len(pending) <= 2 else 'pending_backlog'
    except Exception as exc:
        result['state'] = 'unconfirmed';result['error_type'] = type(exc).__name__
    atomic(directory/'delivery-latest.json',result)
    return result
