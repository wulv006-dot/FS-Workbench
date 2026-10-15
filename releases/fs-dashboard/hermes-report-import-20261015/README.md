# FS共享池成品导入

用户2026-10-15明确允许显示已有HTML/Markdown，标明导入成品、作者、期间、版本，保留原模型任务及费用。本实现新增独立成品目录，不伪造requests/tasks，不建立模型任务，不新增定时。

## 最小接入

- `source/imported_reports.py`：目录和不可变HTML/Markdown，位于FS根目录的同级 `imported-reports/`，不在Hermes Desktop可写的`/fs`绑定里。仅服务器管理员的CLI能收录；网页没有通用写文件API。
- `source/controller.py`：既有GET路由追加成品列表及读取，沿既有登录与共享权限。生成、模型、费用方法及服务器已有management_context接入保留。
- `source/brain.js`：共享池合并显示成品，按报告类型筛选；阅读、下载保留原文。HTML在无same-origin的sandbox内运行，保留交互，禁止访问FS登录页面。
- 成品状态`IMPORTED`，ID为`import-`前缀；无task_id、run_id、model_generated伪标识、模型费用。当前成品不进入旧任务追问、删除和回收流程，后续新版本独立登记、旧版保留。

## 导入

先运行CLI预览并核对文件及manifest哈希；正式执行需提供 `--apply --expected-source-manifest-sha256 <预览值>`。已有目录时，还需 `--expected-catalog-sha256 <当前目录SHA>`。只接受清单里的HTML和Markdown配对、UTF-8、受限文件大小和准确哈希，拒绝目录穿越、软链接和冲突覆盖。

内容相同、作者/版本/期间相同即复用原ID，不新增记录；新版本独立ID。工件先写入、目录最后原子更新，失败不冒认已入池。目录和工件可单独备份；回退不恢复或覆盖任务数据库。

## 验证与发布

`python -m unittest discover -s hermes_report_import_20261015 -p 'test_*.py'`

`node hermes_report_import_20261015/test_import_ui.cjs`

沿原release_navigation发布锁、admission fence、provider锁、CAS、备份与回退；仅3个活动目标，新增1个模块。只需重启消费控制器的fs-business-range，其他业务和Hermes Desktop保持。私库候选及最终SHA另记交付说明；测试通过不等于已上线。
