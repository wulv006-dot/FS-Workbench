> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# 两轮review后的候选修复

两份原始审查及其证据保留外部归档。以下均仅本候选，待完整SHA增量复审；没有生产验证或部署。

| 发现 | 具体修复 | 已执行证据及边界 |
| --- | --- | --- |
| S01 NBA危险默认 | 默认127.0.0.1；缺身份拒绝；WRITE_READY仅显式true；POST/JSON/admin名单/Origin/逐次确认/有限正价格；Python文件写入也要求开关及确认 | 纯权限与真实HTTP handler VM；真实writer替换mock；受支持proxy/token部署待验 |
| S02 秘密输出 | 删除captcha/token/cookie前缀输出；Node不转发stdout/stderr；上游写入错误为固定代码 | 合成哨兵验证login输出，不读取真实日志或轮换凭据 |
| S03 IGGM SSRF | URL主机白名单、禁userinfo/异常端口/私网与混合DNS；每次连接固定验证IP/TLS原主机；重定向重新校验；三crawler及入口均接入 | URL/DNS/连接/重定向纯mock和实际crawler无网络拒绝；未向生产发送攻击 |
| S04 外部FC身份提升 | 内部门户只承认自身有效签名与现存登记，不从FC外部门禁回退提升dashboard身份 | 提取真实verify方法，合成内部/外部/失效身份矩阵；不是生产会话或真实全角色验收 |
| S05 MLB路径边界 | 重复解码、严格组件、realpath共同根、拒链接；handler接入 | 临时同前缀兄弟目录/编码穿越拒绝；Windows符号链接创建受限跳过，Linux与TOCTOU残余另验 |
| S06 运行文件 | NBA_DATA_DIR外置、私有默认文件模式；部署凭据不自动查源/CWD、hub配置显式外置；补ignore和静态包拒绝 | 原始cookie/token/config从未复制；真实权限未修改；既有文件chmod不作为本轮已验证事实 |
| S07 发布内容 | 静态扩展允许清单、运行/凭据路径与内容拒绝；client与server共用策略；全部ZIP/CRC/重复/层级/体积验证后才写；--no-exclude不能绕过 | 合成敏感ZIP在首个写入前拒绝；仍依赖可信发布者，同源任意JS风险非本轮架构隔离已解决 |
| S08 备注XSS | 备注、站点/用户、日志文本和链接属性按HTML文本转义 | 合成恶意备注/数据库字段测试；真实浏览器未执行 |
| S09 发布依赖 | 正常/回滚/恢复均要求精确唯一七路径与64位SHA，保留锁、账本、rename前复查 | 原16项与新增缺失/空/重复/错路径/坏SHA用例；全临时目录，无生产写入 |

F1/F4：D4 shelf_patch/build_dashboard已按审查源SHA补入，后者是ARPG离线生成器，非退役dashboard collector。F2：FC DOM、预览py/sh、清缓存sh四源补齐；仅保存源码，未调用浏览器/清缓存/权限脚本。F3由S01/S02覆盖。F5：外置rev25/15档只读迁移前置合同与合成5用例，缺实际批准数量向量时拒绝，不恢复默认18档、不每轮删档、不改全局引擎默认。

功能P2：准确区间单次请求含JSON解码30秒、整体240秒，父级abort联动，清理监听器；合成202/429、409/422、timeout/abort/race、null与0验证。v7模板旧利润说明/UTC注释尚保留以保持受控精确重建SHA；计划未来新版本整理文案，不声称本轮已改或可直接重建部署。

Players：来自当前本机source_manifest的cloud.9 45源逐SHA匹配，未取九历史目录的最高名。任务台web三源、NBA/MLB前端补齐；MLB候选移除内嵌Basic凭据，改同源既有会话；NBA候选不收URL token、不按字符串前缀外发token，写价加明确逐次确认。新增源尚待增量安全/功能复审及完整运行路径验收。

不视为解决：原tar秘密有效性/轮换；真实只读/外部角色；有效unit/drop-in与容器入口；15档真实数量清单/三公开页；完整平台端到端；Ponytail具体保护实现。没有恢复旧publisher、改生产auth/账号/价格/timer、Git或网络权限。
