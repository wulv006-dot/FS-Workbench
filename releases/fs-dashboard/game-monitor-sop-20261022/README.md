# Hermes MapleStory 十栏目维护源

当前可发布内容是 `source/index.html` 和 `source/assets/maplestory/` 四张官方图片。`source/daily.js`、`source/fs-integration.js`、`source/fs-integration.css` 是与现场完全相同的配套脚本/样式；本次不修改其逻辑。

## 两种路径不能混淆

| 用途 | 本仓库路径 | 原服务器研究路径 |
|---|---|---|
| 待发布页面 | source/index.html | /profile/game-monitor-sop-20261022/candidate/index.html |
| 冻结基线 | ../game-monitor-news-cards-20261016/source/index.html | /profile/game-monitor-sop-20261022/source/index.html |
| 内容检查 | tools/verify.py、tools/jsparse.py | /profile/game-monitor-sop-20261022/tools/ |
| 模拟渲染 | tests/test_render.cjs（Node标准库） | tools/render_check.py（原Hermes环境） |

基线SHA必须为 `368a40026ca065f40a4133f9157f1d22d1d5325dd524d27de0fd13bce8c8d483`。复用私库既有冻结文件，未复制第二份基线；不会把当前source误当历史基线。AUDIT、SOURCES、VALIDATION、CHANGELOG中candidate路径指原服务器研究目录，不是声称本仓库存在candidate目录。

## 可复现检查

完整检出本仓库后，在本目录运行：

    python -m unittest discover -s tests -p 'test_*.py'
    node tests/test_render.cjs

只需既有Python3.9和Node，不增加依赖。检查覆盖五个数据块隔离、十栏目、草稿标记、图片、版本与技能约束、5个有效内联脚本和2个外部脚本编译，以及页面原函数在模拟DOM中的十栏目输出。原报告将7个script标签统称内联，实际为5内联加2外部，核对记录以此为准。模拟渲染不能代替真实浏览器验收。

## 发布与回退

deploy/prepare_release.py只准备现有不可变publisher的精确候选，依赖宿主已有139资产与发布合同；它不直接apply。真实发布仍沿现有publisher的备份、锁、CAS、读回和nginx检查。回退使用本次publisher生成的备份；本仓库source是新候选，绝不能把它当旧基线复制回生产。研究目录candidate只有在未发布时才可作为临时结果丢弃，不代表删除本仓库源码。

经营建议仍是页面可见的待确认草稿，不执行调价、上架、投放或规则变更。原周六00:05情报采集保持；已启用的00:20服务器Hermes任务仅做栏目巡检与候选维护，发布状态与自然周期单独验收。原PDF、版本和实际计划见content-standard-20261022.md；源事实与技能见SOURCES.json、CLASS-SKILLS-REVIEW.json。工具截图/访问量、有效成本/竞品价、关键词量的缺口如实保留。

CI隔离适配：原73项合同拆为Python70项与Node3项语法合同（实际编译5内联+2外部），全部覆盖保留。Node使用标准vm.Script，不从隔离Python测试启动子进程，不改变全局隔离规则。
