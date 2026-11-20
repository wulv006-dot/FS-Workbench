"""Dated, private evidence for the existing preparation and report consumers."""
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import hashlib
import json

TZ = timezone(timedelta(hours=8))
ROOT = Path('/var/lib/fs-hermes-fc/fs/nightly-data')
VIP_REPORT_ROOT = Path('/var/lib/fs-hermes-fc/native')
FALLBACK = time(2, 0)


def save_book(day, kind, start, end, book, brief, root=ROOT):
    from source_snapshots import SnapshotStore, atomic, encoded
    store = SnapshotStore(root / day)
    store.directory()
    value = dict(contract='fs-nightly-evidence-v1', day=day, kind=kind,
                 period={'start': start, 'end': end}, snapshot_id=book.capture_id,
                 saved_at=datetime.now(TZ).isoformat(), brief=brief, evidence=book.evidence)
    raw = encoded(value)
    version = hashlib.sha256(raw).hexdigest()
    artifact = store.root / (version + '.json')
    if not artifact.exists():
        atomic(artifact, value)
    elif artifact.read_bytes() != raw:
        raise ValueError('nightly_immutable_evidence_conflict')
    entry = dict(kind=kind, period=value['period'], sha256=version,
                 file=artifact.name, snapshot_id=book.capture_id,
                 status=brief['collection_readiness']['status'],
                 gaps=brief['collection_readiness']['gaps'])
    atomic(store.root / (kind + '.json'), entry)
    return entry


def preparation_gaps(now, kind, source_root, root=ROOT):
    from source_snapshots import SnapshotStore, preparation_complete
    from nightly import closed_period
    day = now.astimezone(TZ).date()
    try:
        wanted = kind
        if kind not in ('management','management_weekly'):
            path = source_root / ('preparation-' + day.isoformat() + '.json')
            value = SnapshotStore(source_root).read(path)
            if value.get('day') != day.isoformat() or value.get('status') not in ('ready', 'partial'):
                return ['nightly_preparation_not_finished']
            rows = [r for r in value.get('results', []) if r.get('kind') == wanted]
            if len(rows) != 1 or not rows[0].get('native_statuses') or not preparation_complete(rows):
                return ['nightly_' + wanted + '_source_gaps']
        store = SnapshotStore(root / day.isoformat())
        entry = store.read(store.root / (wanted + '.json'))
        version = entry.get('sha256', '')
        if len(version) != 64 or any(c not in '0123456789abcdef' for c in version):
            raise ValueError('nightly_evidence_version')
        artifact = store.root / (version + '.json')
        evidence = store.read(artifact)
        start, end = closed_period(day, wanted)
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != version or evidence.get('day') != day.isoformat() or evidence.get('kind') != wanted or evidence.get('period') != {'start': start, 'end': end} or entry.get('status') != 'ready':
            raise ValueError('nightly_evidence_integrity')
        return []
    except (OSError, ValueError, KeyError, TypeError):
        return ['nightly_evidence_missing_or_invalid']


def report_note(now,kind='daily'):
    day = now.astimezone(TZ).date().isoformat()
    return (' 服务器固定归档入口：/fs/nightly-data/' + day +
            '/；按报告种类读取指针及其SHA对应的不可变证据。FS研究任务使用已注册的同区间证据与计算工具；'
            '服务器原生聊天可直接读该目录。先复用，再自主调用现有只读工具补缺及计算；'
            '不得将准备完成等同于所有指标最终稳定，不改原始事实、价格或业务状态。')


def report_context(now,kind='daily',warnings=()):
    """Server-owned evidence travels in the existing runner context, not the user question."""
    from nightly import closed_period
    from source_snapshots import archive_status
    start,end=closed_period(now.astimezone(TZ).date(),kind)
    query=dict(start=start,end=end,**({} if kind in ('management','management_weekly') else {'profile':'FC27'}))
    context = dict(archive_status=archive_status(query),preparation_gaps=list(warnings),
        rule=('归档分项观察不代表区间完整，无需等待整轮归档。'
            ' 继续使用已存可用证据，按分项说明缺失、原因、重试时间或明确停止；未知不填零，不重复启动正在进行或结果未知的采集。')
        + ' 缺失数据不阻塞本次发布。有可比趋势及已核相关证据才可推算；逐项标注“预估，真实数据暂未提供”，说明依据、方法、假设、范围和不确定性。无依据则保留未知。预估与真实数值分开，不能写回真实归档；回看此前估计，取得同范围真实值后核对误差并追加修订，保留原稿，不重放旧任务。')

    if kind == 'weekly':
        end_exclusive = datetime.fromisoformat(end).replace(tzinfo=TZ) + timedelta(days=1)
        try:
            from vip_maintenance import read_weekly_report
        except ImportError:
            context['vip_maintenance'] = dict(status='unavailable', week=start, reason='vip_module_unavailable')
        else:
            context['vip_maintenance'] = read_weekly_report(VIP_REPORT_ROOT, start, end_exclusive)
        context['rule'] += (' FC27 大客维护章节使用服务端 vip_maintenance 聚合。报告已联系、自然回流、'
                            '联系后七天付款人数及已核美元金额，交代未满七天、覆盖缺口及反馈原因。'
                            '英美与全国家优选分别列示，客户可能重叠，不将两个范围相加。'
                            '以成熟且有覆盖的被联系人作七天比例分母。只有先后顺序，不能归因为维护挽回。')
    return context
