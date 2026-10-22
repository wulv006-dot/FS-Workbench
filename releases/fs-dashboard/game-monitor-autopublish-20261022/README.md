# 游戏监控台静态内容自动发布

用户2026-10-22授权Hermes按既定SOP持续更新静态内容，沿用现有CI、备份和发布校验。仅游戏监控台内容写入；原官方情报/News采集、业务写入、身份、权限、价格规则与通知保持。

## 链路

原Hermes计划6534331b5100（周六00:20北京）读取标准与`/profile/game-monitor-maintenance/live-{baseline,data}.json`，按当前版本研究必要来源，把纯JSON栏目更新原子写入同目录`request.json`。无实质变化时不提交。不接收模型HTML、脚本、命令、目标路径或Git分支。

原宿主`fs-hermes-ops-bridge`五分钟任务在完成原巡检后调用固定controller一步：当前页面CAS→纯数据安全/十栏/来源检查→固定分支PR→当前head/base正式pr-fast→合并→合并字节读回→原不可变publisher inspect/apply→备份/锁/CAS/nginx→147发布对象及保护路径、路由读回→回写Hermes状态。非目标游戏和可执行代码保持。各次请求及写入意图存宿主`/var/lib/fs-hermes-ops/game-monitor/runs/<run_id>`。

`source/contract.py`重用既有JS字面量解析器，仅替换目标游戏的字面量对象。`source/publication.py`仅适配原publisher的数据常量和清单，原实现逐字节复用。`source/controller.py`复用原GitHub身份与受保护合并，不复制或暴露token。`source/host.py`是原bridge的最小追加候选，私库规范位置仍为`releases/fs-dashboard/hermes-ops-20261020/source/host.py`，本模块私库不存第二份。

## 请求

字段固定为schema、run_id、base_sha256、updates、sources、summary。run_id为UTC `YYYYMMDDTHHMMSSZ-8位随机十六进制`；updates按现有游戏key与game/playbook/tools/guide/intel分块提交完整替换对象，通常只提交确实变化的一块。主档身份和events不可修改；其余游戏字节不改。新增事实每个游戏有HTTPS来源、真实抓取时间、版本、摘要与official/community/judgment类别。业务建议保持页面可见的待确认草稿，不触发任何业务writer。

维护可使用既有本地资产或有来源的HTTPS图片；本入口不安装或执行模型产出的代码，不上传新二进制资产。所有十栏检查必须满足，缺数据如实写明；不以开关关闭或删除栏目处理。

## 检查和异常

完整私库检出中执行`python -m unittest discover -s tests -p 'test_*.py'`和`node tests/render.cjs`。无candidate时引用既有MapleStory规范源做真实渲染；有candidate时检查实际请求、before/after、proof与目标游戏十栏。复验不改审计文件。

PR创建/merge/rebase/publish前保存状态。未知创建先查原分支/PR；未知merge查原PR；未知publish只查原stage、备份journal与实际SHA，不重放apply。CI失败、source/route漂移或同模块并行冲突保留证据并暂停该请求，不影响原巡检和采集。其他main变更无本模块冲突时，合并最新base并重新跑正式CI。当前请求未完成前不覆盖为新请求。

自动文件/路由读回与独立真实浏览器验收分开；本次用户指定完整流程须另外实际打开页面确认。首次手动触发完整链不称为后续自然周期成功。
