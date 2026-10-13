"""Load a fixed reviewed method bundle. Skills cannot add execution authority."""
import hashlib
import json
from pathlib import Path

ACTIVE = ('skills/fs-fc-operations-analysis/SKILL.md',
          'skills/fs-fc-operations-analysis/references/methods.md')


def load_bundle(root):
    root = Path(root).resolve()
    manifest = json.loads((root/'skills/manifest.json').read_text('utf-8'))
    if manifest.get('permissions_added') != [] or manifest.get('active_skill') != 'fs-fc-operations-analysis':
        raise ValueError('skill_authority')
    if manifest.get('hermes_commit') != '71d34bad1045610252eda02ee79549436896e784':
        raise ValueError('skill_runtime_pin')
    files = {r['path']: r for r in manifest['files']}
    texts = []
    for name in ACTIVE:
        path = root/name
        if path.is_symlink() or root not in path.resolve().parents:
            raise ValueError('skill_path')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != files[name]['sha256']:
            raise ValueError('skill_changed')
        texts.append(data.decode('utf-8'))
    fingerprint = hashlib.sha256(json.dumps([files[n] for n in ACTIVE], sort_keys=True).encode()).hexdigest()
    return {'version': manifest['version'], 'sha256': fingerprint,
            'text': texts[0], 'methods_text':texts[1], 'permissions': []}


def prompt(bundle, task):
    return ('你是 MMOEXP FC 的只读经营调查 Agent。仅能使用本次明确注册的 FS 工具。'
            '技能定义方法，不授权终端、任意SQL、业务写入、外网或消息。'
            '先读数据目录和历史未结事项，形成竞争解释，自主按线索追加查询和验证，'
            '最后给具体经营对象、动作条件、风险和复查标准。允许有据数字和足够长的专题，'
            '不凑三条。不要把工具不可用写成已查过。\n'
            '已加载方法版本：'+bundle['version']+' / '+bundle['sha256']+'\n'+bundle['text']+
            '\n本次任务：'+json.dumps(task, ensure_ascii=False, sort_keys=True))
