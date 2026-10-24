# 球员任务记录默认显示最近5条

仅改任务列表渲染：按原接口倒序直接显示前5条，其余放入默认关闭的原生 details/summary；少于等于5条不出现折叠栏。原查看结果回调和完整逐模型结果保持，空列表仍显示暂无任务；不删除历史、不改接口返回范围和数据库。

本次两文件生产差量为 app.js 与 VERSION，目标 cloud.14，基于活动 cloud.13.1；保留其按需唤醒、仅派发前会话恢复的原请求一次重试、600秒空闲退出及退役候选timer，不采用私库根目录历史cloud.11.1覆盖现场。规范源/运行路径及前后SHA见 SOURCE-MAP.json。这里只归档当前活动前端精确差量，不接管其它尚未回补的整个运行模块。

检查：Node覆盖空/1/5/6/20条、最新5条/更早完整折叠、原顺序、默认关闭、刷新替换及新旧查看结果回调；原推荐确认按钮检查和JS语法通过。既有 pr-fast 增加本目录检查，无新workflow。原生折叠遵循 modern-web-guidance/html 的“place <summary> as the first child of <details>”，沿用当前样式，不新增组件或共享CSS。

用户已明确批准 publication-manifest.json 对应两文件清单。发布沿现有Players publisher及原deployment.lock、活动49文件/镜像/配置CAS、空闲检查、备份和回退，保持原数据库/执行账本和写入权限；只更新镜像引用。精确发布/真实页面结果在项目 docs/fc27-players/history-collapse-20261024/，实际结果与CI分开记录。旧manifest不可重放，未来发布先核时下活动基线。无业务知识影响和Notion写入。
