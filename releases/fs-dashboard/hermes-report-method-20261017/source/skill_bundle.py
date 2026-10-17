"""Load a fixed reviewed method bundle. Skills cannot add execution authority."""
import hashlib
import json
from pathlib import Path
from report_tracks import track_for_question

ACTIVE = ('skills/fs-fc-operations-analysis/SKILL.md',
          'skills/fs-fc-operations-analysis/references/methods.md',
          'skills/fs-fc-operations-analysis/references/metric-governance.md',
          'skills/fs-fc-operations-analysis/references/report-contract.md')


def load_bundle(root, *, question='', mode=None):
    from report_method import method_bundle
    return method_bundle(track_for_question(question, mode))


def prompt(bundle, task):
    role=('你是 MMOEXP FC 的只读竞品与定价研究 Agent。重点研究 Coins 与 Items 的市场行为、竞品网站比较和市场机会；经营状态只作辅助背景。'
          'Coins 与 Items 分开说明实际可比覆盖。缺少有效成本或同条件竞品实价时，继续给有据市场判断、研究方向和补证行动，不推荐具体新售价。'
          if bundle.get('report_track')=='pricing' else
          '你是 MMOEXP FC 的只读经营调查 Agent。日报、周报、月报重点是宏观经营策略、运营动作、专题与促销规划、履约和积压分析；价格线索只作经营专题的辅助。')
    return (role+'报告首先服务老板决策，用通俗中文给主判断、把握程度、优先动作和反转条件。'
            '执行用户实用审校标准：大体90%以上可验证/覆盖是质量目标，允许不改变主方向的小误差和局部未核平。'
            '有核心依据就给合理判断，不因缺少最终因果证明退回满篇无法判断；缺项可能颠倒方向时才暂停相关建议。'
            '不伪造已测得的90%置信度。详细来源与口径放附录，正文只留必要说明。仅能使用本次明确注册的 FS 工具。'
            '技能定义方法，不授权终端、任意SQL、业务写入、外网或消息。'
            '先读数据目录和历史未结事项，形成竞争解释，自主按线索追加查询和验证，'
            '最后给具体经营对象、动作条件、风险和复查标准。允许有据数字和足够长的专题，'
            '不凑三条。不要把工具不可用写成已查过。\n'
            '已加载方法版本：'+bundle['version']+' / '+bundle['sha256']+'\n'+bundle['text']+
            '\n本次任务：'+json.dumps(task, ensure_ascii=False, sort_keys=True)+
            ('\n本次经营周报专用方法：\n'+bundle['weekly_method_text'] if bundle.get('weekly_method_text') else ''))

