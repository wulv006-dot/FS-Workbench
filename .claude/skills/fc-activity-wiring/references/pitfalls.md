# 已踩过的坑

按"症状 → 原因 → 做法"列。都是 2026-11-16 真实遇到的。

## 页面与结账

- **换一套阵容确认报 `OPERATION_CONFLICT. No successful checkout is confirmed.`**：不是购物车里有东西。`sessionStorage` 的页面操作记录 `fs-native-page:<活动>:<页面>` 的签名里含所选阵容，成功交接后没有释放，同标签页换阵容就冲突，且发生在任何 `Cart/add` 之前。修复在 `checkoutPublished`：上一次操作的 `fs-native-cart:<id>` 状态以 `navigation_attempted` 开头（已加购并跳转）时，不同阵容开新操作；同一阵容仍按原样重放（不重复加购）；UNKNOWN/未完成仍然阻断。**不要清空访客购物车**，会删掉访客自己放的东西，也解决不了问题。
- 同一阵容再次确认会重放：提示"正在打开购物车"但不跳转也不加购，这是现有测试规定的行为，改它要连带改万圣节 `halloween-reveal.test.mjs`。
- 整组页（Trio/SBC）的卡片在价格暂不可用时曾残留灰色"Purchasing unavailable"单张按钮。整组卡片任何状态都不渲染按钮，只显示小标签；唯一的控件是整组按钮，价格没好时置灰，已选中的整组仍可移除。
- SBC 服务不能单独进清单：只有整组添加后才随两位搭档一起进入。
- 登录失败时界面像"卡死"：旧实现只显示灰字且清空密码。现在红框提示、输入保留、按钮恢复、15 秒超时。邮箱登录字段要与主站完全一致（不带 `loginbindkey`）。
- 第三方登录跳回后仍是未登录、令牌留在地址栏：必须按 `apis-and-fields.md` 的方式立即去掉令牌并交给 `/ajax/html` 换会话。
- 券领了但购物车没自动选中：要写 `pending_member_coupon_id`（会员券 ID），不是券模板 ID，也不是优惠码。

## 追踪

- 改了追踪器但线上没动静：改错了文件，线上用 `seasonal/activity-analytics.js`。
- 新事件没有进看板：`server.mjs` 的 `names` 和 `fields` 没加，或 `funnel-core.cjs` 的放行事件列表没加。
- 漏斗测试里计数是 0：不同访问的事件用了相同 `event_id`，被去重了。

## 后端与归因

- `memberCouponLog` 的 `status` 有 0 和 1 两种，不要把 0 当"未知状态"报错；0 是未付款。
- 个别已付款的用券记录在订单列表里查不到：按日志状态和金额，不要整体失败。
- `user.MemberCoupon` 对共享 Admin 账号返回 401，这不是接口坏了；不依赖它也能做使用与转化。
- 发布时报"outside campaign scope"或后端文件被拒：新 Python 文件不在 `publish.py` 的白名单里。
- 日志金额都是美元（订单币种可能是 GBP/MXN），不要再换算。

## 环境与工具

- Windows 上 Node 把 `/tmp/…` 解析成 `D:\tmp\…`；传给 Node 的文件放 scratchpad，用 Windows 风格或相对路径。
- 长文件内容别用 heredoc 里夹引号写：容易被 shell 吞掉。用 Write 工具写文件，再用小脚本做替换。
- 工作区文件是 CRLF、仓库内是 LF：用脚本改文件时先读出是否含 `\r\n`，替换后按原换行写回；`Edit` 对多行锚点可能匹配不上，多行替换用脚本，要求锚点唯一，不唯一就报错。
- 在 `git stash` 后跑基线要用 `-u` 才包含新文件，跑完记得 `stash pop`。
- 删除目录之类的操作可能被权限拦截；被拦就不要绕，告诉用户。
- 写记忆文件时目录名是 `…FS-Workbench` 里连字符，不是路径分隔符。

## 授权与隐私

- Chrome 会把用户的真实密码自动填进测试表单。不要提交；用 JS 清空，或用替换登录函数的方式测 UI。
- 用户的 Admin 令牌只能做只读请求，不打印、不落盘。
- 统计同意是访客本人的选择，验收时不点。
