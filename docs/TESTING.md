> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

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
