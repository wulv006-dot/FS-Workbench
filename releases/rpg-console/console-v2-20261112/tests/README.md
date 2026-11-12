# 控制台回归测试

从仓库根目录运行，Python 3.9 或以上。依赖准备放在 CI 网络隔离之前：

```sh
python -m pip install -r releases/rpg-console/console-v2-20261112/tests/requirements.txt
python -I -B releases/rpg-console/console-v2-20261112/tests/run.py --group console
python -I -B releases/rpg-console/console-v2-20261112/tests/run.py --group rpg
```

`--group all` 连续运行两组。执行入口直接使用 `tools/pr_fast.py` 的 `units`，保留外网与子进程禁止、失败/错误/跳过/零测试均失败的规则。仓库改动分组已接入 `rpg-console`，原 `rpg` 组保持。

- 新组 70 项：参数 13、配置 API 16、页面与真实消费者集成 11、独立审阅回归 4、发布器 26。
- 原 RPG 组：工具合同 10、WoW v5.4 规则 46、本机优先采集 6。完整 checkout 需包含 `aion2_dd373_local_collect_20261006`，不能因 sparse 缺文件跳过合同。
- `fixtures/settings.json` 是手写的最小业务配置，没有凭据、真实商品/区服映射、链接或数据库。API 鉴权排除测试中的标记字符串明确为虚构。
- `fixtures/pricing_expectations.json` 固定改版前 v5.4 纯函数在模拟输入上的输出：40 个库存组合、每组合 4 个上限场景，以及两个虚构商品的引擎决策。运行不读取历史源码或生产配置。
- 数据库、配置保存/恢复和发布器文件测试仅在 `TemporaryDirectory` 中运行。发布器远程端用内存假对象；其真实 Python 文件替换脚本在临时目录内用 `exec` 执行，保留参数解析、Unicode 往返、CAS 和备份恢复验证，不启动 SSH 或子进程。

WoW 旧测试已按现行 v5.4 更新：150G/50G 分档、25%/30%/35%、全部有效出货挂单、最终售价择低、有货 1.60 上限和双源确认无货 2.99 例外。退役的 IGGM 定价函数测试改为当前双源链路不额外取 IGGM 的合同；其他本机优先采集测试保留。

本地验证使用 Python 3.12 和预先安装的 Flask 依赖，在相同 pr-fast 离线守卫下完成；不等同于线上部署验收。
