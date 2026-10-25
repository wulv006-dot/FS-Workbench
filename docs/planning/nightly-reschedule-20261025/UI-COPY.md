# FS夜间说明与已发布排程同步

实际wulv页面已经显示新日报01:40、管理02:10等服务器时间，但静态概览和说明残留07:00/06:59及06:30。仅对当前线上完整HTML做5处文本替换：概览07:50、准备00:10/00:20/00:35/00:50及对应文字、缓存07:40、停止新准入07:49与保存终态07:50。完整tag及attribute序列逐项一致，脚本、资产引用、表单、权限、主题、报告iframe和事件均保持。没有新增前端逻辑，不单独新增模仿实现的测试。

源`releases/fs-dashboard/nightly-reschedule-20261025/ui/brain-index.html`→`/var/www/dashboard/fs-home/brain/index.html`，只覆盖此页，复用现有`/opt/fs-hermes-ops/release_ui.py`及其冻结base，独立manifest/CAS/备份发布，业务worker/timer动作0。当前报告模型不被重启。

modern-web-guidance已搜索静态HTML文案、读取html指南；仅文本修正，无新增网页模式或API可套用，原语义和交互结构保留。正式CI和实际刷新读回另验。
