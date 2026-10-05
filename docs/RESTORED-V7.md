> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# 统一经营页 v7 恢复代码

2026-10-05 11:31:56 北京时间已通过现有受控网关恢复生产；版本20261005-restore-v7，完整HTML SHA为1d6a6084d9c505f19cb12c9e856c652feb53af9a2f2f54e61c9a638b6e416f5a。相对已批准v6仅改发布标记，未部署其它代码或改变认证、价格、采集/Google/周报计划。

本候选新增 `共享资源/MMOEXP统一看板/dashboard.template.html`。它保留恢复版全部代码，但将既存历史PROFIT业务聚合JSON替换为唯一占位符；真实运行数据没有加入候选。模板本身不能直接当部署HTML，不能把占位符缺失说成线上功能被删。

本地构建 `python tools/build_business_html.py --private-profit <仓库外受控原JSON> --output <仓库外新HTML>` 仅接受契约中精确payload/template SHA，并验证重建HTML等于本次恢复SHA。输入数据和输出均须位于仓库外，拒绝覆盖已有输出；没有网络、上传或部署动作。原JSON保留原字节，不能重新格式化。合成用例 `python -m unittest discover -s tools -p test_business_html_build.py` 不使用真实数据。

当前运行依赖仍是现有登录保护、共享snapshot/准确区间接口及静态资源。旧嵌入PROFIT图表历史数据也留在仓库外；真实管理员近7日利润趋势显示未提供数据，所选区间原生利润率指标可用。本次仅恢复原已批准页面，不补造日利润走势。页面保留利润/销售图、日历和结构容器，已删除的项目利润地图/重复来源表格没有重加。

生产现场与恢复记录在原项目docs/planning/github-collaboration-20261005/dashboard-investigation/，不加入候选真实业务输出或备份。详细缺失依赖和另一台电脑最小文件要求见DEPENDENCIES-AND-OTHER-MACHINE.md。
