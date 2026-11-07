"""One-time, idempotent test-guild onboarding requested by the owner."""
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path('/opt/mmoexp-fc-community')
CHANNEL = '1568260661010497627'
OWNER = '1237241595674361962'
sys.path.insert(0, str(ROOT))
from community import CommunityStore


def main():
    marker = ROOT / 'var/onboarding.json'
    if marker.exists():
        print(marker.read_text())
        return
    database = ROOT / 'var/community.sqlite3'
    if not database.exists():
        raise RuntimeError('Expected initialized community database')
    store = CommunityStore(database, {OWNER})
    now = int(time.time())
    source = f'https://discord.com/channels/1565922092518613064/{CHANNEL}'
    seeds = [
        ('[演示] FC27 机器人使用说明', 'guide',
         '这是功能演示，不是游戏新闻。输入 /fc latest 查看目录，/fc guide content_id:编号 阅读内容。'
         '输入 /fc events 查看活动，/fc join event_id:编号 报名，/fc leave event_id:编号 取消。'
         '回复默认仅自己可见。当前没有实时价格、自动SBC求解或订单查询。'),
        ('[演示] SBC 求助信息模板', 'sbc',
         '这是提问模板，不是已经求解的SBC方案。提交需求时建议说明：挑战名称、平台、预算、'
         '完整要求、可使用球员卡版本和不可交易卡。请勿提供EA密码、验证码或网站订单信息。')]
    ids = []
    for title, kind, body in seeds:
        with store.db() as conn:
            row = conn.execute('SELECT id,status FROM content WHERE title=? ORDER BY id LIMIT 1', (title,)).fetchone()
        item = row['id'] if row else store.draft(OWNER, title, kind, body, source, 27, now)
        if not row or row['status'] == 'draft':
            store.approve(OWNER, item, now)
        ids.append(item)
    event_title = '[演示·无奖励] FC27 机器人报名测试'
    with store.db() as conn:
        row = conn.execute('SELECT id FROM events WHERE title=? ORDER BY id LIMIT 1', (event_title,)).fetchone()
    event = row['id'] if row else store.create_event(OWNER, event_title, 20, now + 86400, now)
    message = f'''**MMOEXP FC Assistant｜试用说明**
本频道用于测试 FC27 机器人。以下演示活动**没有奖励或派奖**。

**先体验**
1. `/fc latest` 查看内容目录。
2. `/fc guide content_id:{ids[0]}` 阅读示例。
3. `/fc events` 查看活动。
4. `/fc join event_id:{event}` 报名；`/fc leave event_id:{event}` 取消。

**你本人管理**
`/fc draft` 填写 title 标题、kind 类型、body 正文、source 来源。
kind：news 新闻 / sbc SBC攻略 / squad 阵容攻略 / guide 通用指南。
source 必须是完整 https:// 链接；原创说明可引用本频道链接。
得到内容编号后，`/fc preview content_id:编号` 预览，`/fc approve content_id:编号` 自行发布到查询目录。
`/fc withdraw content_id:编号` 撤回。发布到目录后用户通过命令查询，不会自动广播。

创建活动：`/fc event-create title:活动名称 capacity:20 hours:24`
capacity 是名额；hours 是从创建起到报名截止的小时数，不是活动开始时间。
查看示例报名报表：`/fc report event_id:{event}`（仅运营可用）。
报表按首次成功报名的频道统计，不是网站订单成交报表。

输入 /fc 后请点击 Discord 弹出的命令并逐项填写参数；以上冒号形式是参数示意。
命令回复仅本人可见。每人每30秒最多8次，请勿连续反复提交。
当前只开放内容和报名功能；会员订单、实时价格与自动SBC求解仍待接入。'''
    token = next(line.split('=', 1)[1] for line in Path('/etc/mmoexp-fc-community.env').read_text().splitlines()
                 if line.startswith('DISCORD_BOT_TOKEN='))
    request = urllib.request.Request(f'https://discord.com/api/v10/channels/{CHANNEL}/messages',
        data=json.dumps({'content': message, 'allowed_mentions': {'parse': []}}).encode(),
        headers={'Authorization': 'Bot '+token, 'Content-Type': 'application/json', 'User-Agent': 'MMOEXP-FC-Pilot/1.0'}, method='POST')
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    state = {'channel_id': CHANNEL, 'message_id': result['id'], 'content_ids': ids, 'demo_event_id': event}
    marker.write_text(json.dumps(state))
    print(json.dumps(state))


if __name__ == '__main__':
    main()
