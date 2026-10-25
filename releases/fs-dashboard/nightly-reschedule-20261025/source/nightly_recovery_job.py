"""Dispatch one native server Hermes read-only investigation per business morning."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

sys.path.insert(0, '/opt/hermes')
from cron.jobs import create_job, list_jobs
sys.path.insert(0, '/fs-source')
from source_snapshots import atomic


def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    if not 70 <= now.hour*60+now.minute < 90:
        print(json.dumps({'status':'outside_recovery_window'})); return
    folder = Path('/fs/nightly-data') / now.date().isoformat()
    marker = folder / 'hermes-recovery.json'
    name = '夜间数据补查-' + now.date().isoformat()
    matches = [j for j in list_jobs(include_disabled=True) if j.get('name') == name]
    if matches:
        if len(matches) != 1: raise ValueError('duplicate_recovery_jobs_reconcile')
        job = matches[0]
        atomic(marker, {'status':'created_readback','job_id':job['id'],'name':name})
        print(json.dumps({'status':'existing','job_id':job['id']})); return
    if marker.exists():
        print(json.dumps({'status':'unknown_no_replay'})); return
    atomic(marker, {'status':'creating','name':name,'at':now.isoformat()})
    prompt = ('用户已授权本次服务器夜间数据故障只读补查。先读取 '+str(folder)+
        '/operations.json、/fs/source-snapshots/preparation-'+now.date().isoformat()+
        '.json 和 /fs-source/data-archive-first.md。优先固定归档证据，再自主调用现有FS只读数据目录、原生统计、营销和订单结构工具补缺；'
        '区分昨日、上个完整周/月、全项目经营与FC单项目。只做本次必要查询，不重复启动正在运行的采集，不重放unknown请求，不改价格、业务、登录、调度或记忆。'
        '最多20分钟；01:30前停止补查。把实际工具结果、缺项、原因和建议修复入口保存为 '+str(folder)+
        '/hermes-recovery-analysis.md，保留证据ID。若仍失败，原五分钟桥将通过原飞书AI协作群以同一事件联系Codex；不要另发重复消息。'
        '本任务不生成正式报告，不填零或捏造数据，不把有文件当已完整。仅对已确认失败且无活动任务的只读查询按原工具重试。')
    job = create_job(prompt=prompt, schedule='1m', name=name, repeat=1, deliver='local', workdir='/fs', attach_to_session=False)
    actual = next(j for j in list_jobs(include_disabled=True) if j['id'] == job['id'])
    atomic(marker, {'status':'created_readback','job_id':actual['id'],'name':name,'at':now.isoformat()})
    print(json.dumps({'status':'created_readback','job_id':actual['id']}))


if __name__ == '__main__': main()
