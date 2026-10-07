> 历史证据：下文结果/来源只属于各自对象和时点，不构成当前全仓QA、上传或另批门槛。当前执行规则只见 [HOTFIX](ops/HOTFIX.md)；先验直接影响，资料后补，不把旧绿或旧失败冒充新候选结果。

## 2026-10-07 本治理合并检查记录

复用并核对PR #3精确检查器原字节，在本机隔离副本完成完整合成检查：185 Python方法，184pass/1Windows所有权skip/0fail-error；182 Python AST、34 JS语法、rev25矩阵及7组Node通过。Windows Python3.14首次Google时区用例因缺tzdata失败，原失败保留；使用现有Codex bundled tzdata/zoneinfo设置仅当前测试进程PYTHONTZPATH后完整复核通过，没有安装依赖、改源码、伪造时区或删除用例。该结果只覆盖本治理所沿用的main业务源码，不能替代PR #2 NBA增量或PR #5注册、真实Linux/身份/生产验收。

最终文档/两清单经精确树、308未变文件原字节及17模块归属检查；完整合成检查输入的业务源码与最终候选字节相同。本次15条路径均为治理文档/JSON，merge条件仅限该范围。PR #2/#3保持draft，未来业务组合树重新核验；空GitHub checks不是正式CI绿色。最终head/tree和实际merge以PR #6读回为准，生产仍未授权。



# 首版候选检查

检查时间：2026-10-05T03:09:56.430834+00:00。新跑的单元用例总数127，跳过1；各组状态见下面JSON。另有Python语法解析、JS语法检查及3组日期/日历/Aion2状态JS合同检查。

所有输入为手工构造或已核实合成向量。原生排行/周报/营销UI旧测试依赖真实业务快照，因此不纳入这些旧测试，也不导入真实fixture。新周报11用例独立验证日期、SHA、来源/同区间、原生四核心保持和端点零值处理。最新range59用例保留原最小旧代码对照；该旧代码不部署。

FC本轮24引擎+12降幅纯合同中，Windows没有os.chown的1项所有权用例明确跳过；不模拟其生产权限通过。文件锁调用在纯组被拒绝，parser既有测试仍mock原生源/锁；Windows不能证明Linux flock/并发部署行为。126后端/210行parity是原发布验收记录，不与本轮新跑数量混同。

无真实账号登录/保存、无生产部署、无采集或价格写入。来自另一台电脑的功能尚未验证。工具只跑安全子集，其他已收录Coins回归需在后续独立Linux测试环境配齐mock认证依赖后再跑，不对其全套覆盖作声明。

```json
{
  "testedAt": "2026-10-05T03:09:56.430834+00:00",
  "productionChanges": false,
  "scope": "isolated Windows source checks and synthetic fixtures; no live account, sampling or price writes",
  "passed": true,
  "results": [
    {
      "check": "python-parse",
      "files": 85,
      "passed": true
    },
    {
      "check": "javascript-parse",
      "files": 22,
      "passed": true
    },
    {
      "check": "parser",
      "testsRun": 59,
      "passed": true,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "failureTypes": []
    },
    {
      "check": "engine",
      "testsRun": 24,
      "passed": true,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "failureTypes": []
    },
    {
      "check": "discount-pure",
      "testsRun": 12,
      "passed": true,
      "failures": 0,
      "errors": 0,
      "skipped": 1,
      "failureTypes": []
    },
    {
      "check": "weekly",
      "testsRun": 11,
      "passed": true,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "failureTypes": []
    },
    {
      "check": "google-collector",
      "testsRun": 7,
      "passed": true,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "failureTypes": []
    },
    {
      "check": "google-details",
      "testsRun": 14,
      "passed": true,
      "failures": 0,
      "errors": 0,
      "skipped": 0,
      "failureTypes": []
    },
    {
      "check": "date-range",
      "passed": true,
      "returncode": 0
    },
    {
      "check": "calendar",
      "passed": true,
      "returncode": 0
    },
    {
      "check": "aion2-state",
      "passed": true,
      "returncode": 0
    }
  ]
}
```

v2新增6项synthetic HTML构建合同测试，命令：`python -m unittest discover -s tools -p test_business_html_build.py`。精确v7私有payload重建仅在受控仓库外核实，不将真实payload放测试fixtures。
