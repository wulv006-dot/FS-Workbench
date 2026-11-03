# 2026 年 11 月经营管理台

正式目标周期 2026-11，25 款，USD 2,000,680。球类 8 款/954,300，综合 6 款/330,500，RPG 11 款/715,880。原表来源与单元格见 targets.json；10 月配置独立保留，不覆盖历史。游戏目录仍保留非 11 月目标的游戏。

COD 使用用户确认的 MW4（Admin1335 / Order1302），WoW Forever，D2R（两边530）。GTA5（Order573/Admin711）与GTA6（两边550）在管理台按一行合计400；只加营收、订单和同口径利润金额，客户数/比率缺乏跨游戏去重不相加。其他新游戏映射取自2026-11-03两个后台的实时游戏目录。

订单/量、利润率和其他二级指标按原表展示并保留口径待核状态；不自动生成利润金额目标，不用旧目标或零补齐。原表经营动作是转义展示文本，不是改价、促销、预算或发信授权。沙盘按正式25项初始化，按用户/月/目标版本隔离草稿，保留重分配、总额校验与导出，支持380等小额和1美元调整。

当前源见 SOURCE-MAP.json。运行时 range_api、admin_summary、business_shipping 共用 management_profiles 的经核实目录；只增加按需目录，不修改原 transaction collector 的定时范围。management_facts、runner 保留原两线程、日更窗口、缓存、文件锁、原回执、快照及模型计划；同日目标版本改变需手动升级并保存旧回执。只有自然日更完成后才能声明自然周期验收。

直接检查（在本目录运行）：`python -m unittest test_november -v`；`node test_sandbox.cjs`；`node test_target_hash.cjs`；Linux 再运行 `python -B check_linux.py`。原 pr-fast 已登记同一组，不另建 workflow。指纹测试直接比较生产 Python 指纹函数与浏览器同算法，避免860000.0/860000序列化差异。

发布沿原 release_navigation_base.py 的锁、逐文件CAS、持久备份和失败回退，新增文件只能在本次精确清单内；先新静态版本再按确切路由切换，保留其他导航块。只修改数据时仅重载Nginx，修改范围读取脚本时只重启原range服务；不改权限、共享会话、FC/RPG writer、计划或预算。超时或unknown先查原planned-release和journal，不换ID重发。回退仅使用对应发布回执及原备份，不能恢复旧整包或数据账本。
