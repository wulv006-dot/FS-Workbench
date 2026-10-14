# Hermes新增测试正式覆盖

PR123本机discover=201，但正式pr-fast显式模块清单只执行189；新增test_admission_hold、test_context_gate、test_browser_ui此前遗漏。补入原Hermes测试组：费用准入和上下文在既有禁外部进程/网络的units运行器执行（200项）；页面Node模拟用独立-I/-B测试脚本运行（1项），避免放宽所有离线单测的subprocess保护。保留其它组/所有原模块/错误与skip传播。正式200+1及固定官方high/max以本PR准确head CI验收，不把189记成201。业务源和生产尚未改变；PR123已合并、未部署，需本修正合并后共同受控发布。
