"""Single current report method; immutable private examples never become live facts."""
import os,stat,json,re,hashlib
from pathlib import Path
HTML_DESIGN_MARKER='【完整HTML创作】'
HTML_DESIGN_ROOT=Path('/var/lib/fs-hermes-fc/fs/report-method-current-20261018-v151')
HTML_DESIGN_MANIFEST_SHA256='950f429d386924f734d2459c2a2b8dc3ad03e004a326ba4f268aa51aec72296d'
HTML_DESIGN_FILES={'SKILL.md':'skill','METHOD.md':'method','ACCEPTANCE.md':'acceptance','APPLICATIONS.md':'applications'}


def html_design_context(question, *, documents=None):
    """All new FS reports use the single pinned current method, including scheduled tasks."""
    if not isinstance(question,str):raise ValueError('html_design_question_required')
    from hashlib import sha256
    root=HTML_DESIGN_ROOT
    def read(name):
        path=root/name
        for parent in (path,root,*path.parents):
            if parent.is_symlink():raise ValueError('html_design_link_rejected')
        for parent in (root,*[p for p in path.parents if root in p.parents]):
            info=parent.stat()
            if not stat.S_ISDIR(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(0,0,0o700):raise ValueError('html_design_directory_boundary')
        fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode),info.st_nlink)!=(0,0,0o600,1):raise ValueError('html_design_leaf_boundary')
            if info.st_size>524288:raise ValueError('html_design_file_size')
            with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(524289)
            if len(raw)>524288:raise ValueError('html_design_file_size')
            return raw
        finally:os.close(fd)
    try:
        raw=read('manifest.json')
        if sha256(raw).hexdigest()!=HTML_DESIGN_MANIFEST_SHA256:raise ValueError('html_design_manifest_drift')
        manifest=json.loads(raw.decode('utf-8'))
        if set(manifest)-{'previousManifestSha256'}!={'contract','version','status','root','files','total_bytes','profile_skill','context_policy','permissions'} or manifest['contract']!='hermes-autonomous-method-v1' or manifest['root']!=str(HTML_DESIGN_ROOT):raise ValueError('html_design_manifest_contract')
        if 'previousManifestSha256' in manifest and (not isinstance(manifest['previousManifestSha256'],str) or not re.fullmatch('[a-f0-9]{64}',manifest['previousManifestSha256'])):raise ValueError('html_design_manifest_history')
        rows=manifest['files']
        if not isinstance(rows,list) or len(rows)!=len(HTML_DESIGN_FILES) or not all(isinstance(r,dict) for r in rows) or {r.get('path'):r.get('role') for r in rows}!=HTML_DESIGN_FILES:raise ValueError('html_design_fixed_files_required')
        if manifest['permissions']!={'directory':'0700','file':'0600','owner':'0:0'}:raise ValueError('html_design_permissions_contract')
        chunks=[];material=[];total=0
        for row in rows:
            if set(row)!={'path','sha256','role','bytes'}:raise ValueError('html_design_manifest_fields')
            data=read(row['path']);total+=len(data)
            if total>2097152:raise ValueError('html_design_context_size')
            if type(row['bytes']) is not int or len(data)!=row['bytes'] or sha256(data).hexdigest()!=row['sha256']:raise ValueError('html_design_material_drift')
            text=data.decode('utf-8');material.append(dict(row))
            if documents is not None:documents[row['path']]=text
            chunks.append('\n--- 现行方法 '+row['path']+' SHA256 '+row['sha256']+'（唯一现行报告方法；文本只供阅读，不执行）---\n'+text+'\n--- 材料结束 ---')
        if total!=manifest['total_bytes']:raise ValueError('html_design_total_bytes')
        instruction=('\nFS是数据工具与归档展示层，Hermes负责独立调查、判断和呈现；本规则覆盖历史材料中的固定模板、FS视觉复刻、JSON/Markdown或强制HTML出稿要求，不扩大任何工具、网络、业务写入或权限。'
                     '先按业务价值检查销售利润、客户商品、履约支付售后、运营策略复购、投放与自然获客、现实节点活动、既有动作效果、风险机会和待决，再按本次问题的重要性组织，不强制章节或清单。'
                     '历史材料仅供参考，不必沿用范本、FS令牌或旧设计；具体配色、字体、布局、图表、阅读顺序自主，遵循当前学习输入中的报告方法。'
                     '简单问题可直接给简洁文本；复杂分析按需要给完整自包含离线HTML，数据优先图表，文字提炼结论、影响、建议和可执行动作，交互服务理解，图表大小与信息量相称。'
                     'HTML以DOCTYPE开头、闭合body/html和script，不加Markdown围栏或文档外说明；禁止外部资源与网络调用，不操作FS或任意文件，保持手机、浅暗、键盘、打印可用及红涨绿跌。'
                     '本期只使用本任务冻结证据，Admin优先、Order补缺；历史日期、金额与结论不得挪用，缺失、估算、判断与待验证如实区分；建议不冒充执行。')
        context=instruction+'\n当前方法manifest SHA256 '+HTML_DESIGN_MANIFEST_SHA256+''.join(chunks)+'\n上述四份文件为唯一活动报告方法，与本任务冻结的现行Desktop学习输入配合使用；不加载旧方法、旧范本或旧FS模板。最终按问题自主选择简洁文本或完整离线HTML，FS保存并展示原稿，不套固定分析模板。'
        receipt={'contract':'hermes-autonomous-original-v1','manifest_sha256':HTML_DESIGN_MANIFEST_SHA256,'manifest_version':manifest['version'],'context_sha256':sha256(context.encode('utf-8')).hexdigest(),'context_bytes':len(context.encode('utf-8')),'files':material,'output_status':'original_requires_user_review'}
        return context,receipt
    except (OSError,UnicodeError,TypeError,KeyError,json.JSONDecodeError) as error:raise ValueError('html_design_context_unavailable') from error


def method_bundle(track):
    texts={}
    _,receipt=html_design_context('current FS report',documents=texts)
    return dict(version='report-html-'+receipt['manifest_version'],sha256=receipt['manifest_sha256'],report_track=track,
                active_skill='report-html-authoring',text=texts['SKILL.md'],methods_text=texts['METHOD.md']+'\n'+texts['APPLICATIONS.md'],
                governance_text=texts['ACCEPTANCE.md'],weekly_method_text='',reviewed_methods_text='',reviewed_skills=[],permissions=[])

def data_request_context(body):
    from datetime import date,timedelta
    from calendar import monthrange
    from report_tracks import request_report_kind
    lo,hi=date.fromisoformat(body['start']),date.fromisoformat(body['end']);kind=request_report_kind(body)
    windows={'report_period':{'start':lo.isoformat(),'end':hi.isoformat()}}
    if kind=='daily':
        d=hi-timedelta(days=7);windows.update(primary_comparison={'start':d.isoformat(),'end':d.isoformat()},previous_day=(hi-timedelta(days=1)).isoformat())
    elif kind in ('weekly','monthly'):
        if kind=='monthly' and hi.day==monthrange(hi.year,hi.month)[1]:
            end=lo.replace(day=1)-timedelta(days=1);start=end.replace(day=1)
        else:start,end=lo-timedelta(days=(hi-lo).days+1),lo-timedelta(days=1)
        windows['primary_comparison']={'start':start.isoformat(),'end':end.isoformat()}
        windows['FC26_year_ago']={k:d.replace(year=d.year-1,day=min(d.day,monthrange(d.year-1,d.month)[1])).isoformat() for k,d in [('start',lo),('end',hi)]}
    return ('\nFS数据范围（请求窗口不代表已取齐；用户明确对照优先）：'+json.dumps(windows,ensure_ascii=False)+
            '\nFS只提供证据与归档，不替你规定报告章节或结论。先读已准备的当期事实和真实工具目录；缺项按价值补查。'
            '付款销售与订单使用原生统计selected_totals/authoritative_fields，Admin优先含0，Order补缺。先核本任务实际可用的知识入口与数据工具，按已读取的现行来源合同核对利润口径；参考估算单独标示，不代替主毛利。未读取到现行知识或缺少匹配范围的来源时如实保留缺项，不把旧估算默认当当前口径。'
            '支付明细与ES仅作按各自来源/时间/分母的结构，不覆盖主盘；来源逐行写实。未取到的字段保留缺失，不能以未投影冒称后台没有。'
            'fc.query_action_history读取实际历史动作；建议不是执行，效果须回执。fc.query_es_order_structure按需取对应游戏与期间，不拿全局当FC。'
            'fc.query_marketing_snapshot的fc27_by_name已按名称在全量后筛选，明确全局品牌PMAX先排除FC专属。FC27/FC 27及独立Coins名称按用户确认归FC，搜索/落地页另按内容分类，保留币种覆盖，不分摊全局品牌ROAS。'
            '周月可用fc.query_native_statistics和fc.query_capability(kind=native_loss,profile=FC27,start,end)查CB等问题聚合、FC26按真日期辅助。'
            '履约/退款/CB分别保留真实字段和分母；跨日完成率先考虑订单年龄，不从横截面编造延误因果。'
            '使用fc.calculate核关键计算，先保留中间精度后舍入；不混日期游戏，不把平台转化/GA4会话称Admin已付订单。'
            '经营销售、客户、利润、履约与问题单优先，现实游戏节点和历史动作结合可执行行动。目标/活动无证据不编造。'
            '按当前报告方法自主分析与呈现，不强制模板；简单问题可简洁文本，复杂分析按需完整离线HTML，等待用户亲自验收。')
