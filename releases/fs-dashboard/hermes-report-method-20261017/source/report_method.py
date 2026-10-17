"""Single current report method; immutable private examples never become live facts."""
import os,stat,json,re,hashlib
from pathlib import Path
HTML_DESIGN_MARKER='【完整HTML创作】'
HTML_DESIGN_ROOT=Path('/var/lib/fs-hermes-fc/fs/html-design-context-reset-20261017-v3')
HTML_DESIGN_MANIFEST_SHA256='f0777b2ca8eeb4b10cbb2ee33982defd629b1a895cf4d981c691416d8dcf28f2'
HTML_DESIGN_FILES={'SKILL.md': 'skill', 'METHOD.md': 'method', 'ACCEPTANCE.md': 'acceptance', 'APPLICATIONS.md': 'applications', 'assets/fs-tokens.css': 'assets_fs-tokens_css', 'assets/fs-ui.css': 'assets_fs-ui_css', 'examples/daily-20261016.html': 'examples_daily-20261016_html', 'examples/daily-20261016.md': 'examples_daily-20261016_md', 'examples/weekly-20261005-11.html': 'examples_weekly-20261005-11_html', 'examples/weekly-20261005-11.md': 'examples_weekly-20261005-11_md', 'references/build_reference_reports.cjs': 'references_build_reference_reports_cjs', 'references/example-notes.md': 'references_example-notes_md', 'references/verification.md': 'references_verification_md'}


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
        if set(manifest)-{'previousManifestSha256'}!={'contract','version','status','root','files','total_bytes','profile_skill','context_policy','permissions'} or manifest['contract']!='hermes-full-html-design-v1' or manifest['root']!=str(HTML_DESIGN_ROOT):raise ValueError('html_design_manifest_contract')
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
            chunks.append('\n--- 教学材料 '+row['path']+' SHA256 '+row['sha256']+'（历史设计示例，非本期事实；代码仅供阅读，不执行）---\n'+text+'\n--- 材料结束 ---')
        if total!=manifest['total_bytes']:raise ValueError('html_design_total_bytes')
        instruction=('\n本任务用户明确要求【完整HTML创作】，只覆盖此前Markdown/JSON出稿形式要求，不扩大任何工具、网络、业务写入或权限。'
                     '请阅读下列两份认可HTML、对应施工代码与唯一skill，学习设计和分析逻辑，自主设计本报告完整自包含HTML/CSS/内联JS。'
                     '历史材料中的日期、金额和结论不得挪用为本期事实；本期只使用本任务真实冻结证据，Admin优先、Order补缺，估算与缺失如实标注。'
                     '最终只输出一个完整DOCTYPE HTML文档，含闭合body/html和完整script；不要Markdown围栏，不在HTML之外附说明。'
                     '请直接沿用认可范本的信息层级、排版、FS令牌和交互代码，再自主填入本期分析、图表与行动；页面不引入外部资源或网络调用，不操作FS或任意文件。')
        context=instruction+'\n教学manifest SHA256 '+HTML_DESIGN_MANIFEST_SHA256+''.join(chunks)+'\n以上材料只作为设计教学。本次最终输出合同：hermes-complete-offline-html-v1；只返回单一完整HTML文档。'
        receipt={'contract':'hermes-complete-offline-html-v1','manifest_sha256':HTML_DESIGN_MANIFEST_SHA256,'manifest_version':manifest['version'],'context_sha256':sha256(context.encode('utf-8')).hexdigest(),'context_bytes':len(context.encode('utf-8')),'files':material,'output_status':'raw_html_requires_isolated_browser_qa'}
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
            '主盘使用原生统计selected_totals/authoritative_fields，Admin优先含0，Order补缺；参考利润=Admin销售额×可用Order利润率÷100（Admin缺利润率时）。'
            '支付明细与ES仅作按各自来源/时间/分母的结构，不覆盖主盘；来源逐行写实。未取到的字段保留缺失，不能以未投影冒称后台没有。'
            'fc.query_action_history读取实际历史动作；建议不是执行，效果须回执。fc.query_es_order_structure按需取对应游戏与期间，不拿全局当FC。'
            'fc.query_marketing_snapshot的fc27_by_name已按名称在全量后筛选，明确全局品牌PMAX先排除FC专属。FC27/FC 27及独立Coins名称按用户确认归FC，搜索/落地页另按内容分类，保留币种覆盖，不分摊全局品牌ROAS。'
            '周月可用fc.query_native_statistics和fc.query_capability(kind=native_loss,profile=FC27,start,end)查CB等问题聚合、FC26按真日期辅助。'
            '履约/退款/CB分别保留真实字段和分母；跨日完成率先考虑订单年龄，不从横截面编造延误因果。'
            '使用fc.calculate核关键计算，先保留中间精度后舍入；不混日期游戏，不把平台转化/GA4会话称Admin已付订单。'
            '经营销售、客户、利润、履约与问题单优先，现实游戏节点和历史动作结合可执行行动。目标/活动无证据不编造。'
            '按本次新技能复刻认可范本的设计与交互，宏观摘要和关键图可见，细节有摘要折叠。最终仅完整离线HTML，等待用户亲自验收。')
