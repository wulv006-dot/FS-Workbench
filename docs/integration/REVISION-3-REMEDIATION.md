> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# Revision 3有限修补

范围来自两份revision2完整复审；报告/JSON原件在外部revision3/independent-reviews。旧301集合保持不可变。本轮只在独立candidate_revision3修改，没有连接/部署/变更生产。

| 发现 | 候选修补 | 证据与限制 |
| --- | --- | --- |
| R2-01 FC会话兼容 | portal缺内部登记时仅对归档FCops/Players明确GET/HEAD白名单调用既有8896/verify；只转fc27sess，只发X-Fc27-User/readonly；无X-Auth-*，同名wulv/DY不提升 | test_revision3_contracts四组矩阵；实际FC服务/活跃nginx/用户登录未验。FC页面四内部共享静态引用仍拒绝，见DECISIONS，故模块发布仍阻断 |
| R2-02 NBA计划/响应错绑 | 独立wx/600计划路径；requestId+planSHA+operator绑定回执；curl独立响应文件；全writer/login/cookie生命周期同一锁；先持久pending，未知不重放，完成同ID只回原回执，异hash/actor拒绝 | 实际adminWrite在VM使用两哨兵/延迟fake execFile，Python锁/receipt以TMP实测；无真正子进程写价。Linux多进程/flock/受信运行根另验 |
| R2-03 静态凭据 | JSON解析后递归、转义键/大小写/列表/值识别Cookie、set-cookie、batoken、Authorization Basic/Bearer；拒重复键。HTML/JS扫描仍启发式；明确无凭据placeholder放行 | SYNTHETIC拒绝/全ZIP验证先于任何文件写；client内嵌政策逐字+SHA生成。没有声称任意隐写或同源JS隔离 |
| R2-F1/F2 六行与数量 | 精确id/mid/gid/cid/site_id/aid/unit/title/status；有限正Decimal、按数值唯一、顺序及源/ALL向量保留 | 8迁移用例，六行×9字段缺失/错值负矩阵；参考仍仅带日期数量，不当时下真实读回 |
| R2-F3 四档链 | 16合成向量直用真实Python calculate、JS recompute、Python check_write；rev25准确6–8/5–6/0–5/0–0、三阈值两侧、裁剪两界、赠送与Xbox独立成本、hash/修订/价格篡改 | 6专用测试；不调用save/writer/队列/timer，也不把全局新环境默认改成运行rev25 |

目标检查共47项Python，46通过/1旧Windows symlink skip；3组Node通过。此轮没有重跑全部revision2的170项，不能称新版191全套已实跑。旧核心字节逐SHA保持，语法清单单独保存。Linux所有权/锁/真实proxy/内部只读/FC外部角色/容器/CDP/有效unit/全平台/Ponytail仍未验。

NBA逐轮confirm保持revision2候选交互，不替用户选择是否无人值守；真实生产自动化没有变化。FC限定桥是候选补丁，未新增账户/角色/注册能力，四资源兼容问题不借机开内部页面/数据。旧publisher刻意排除，六补源/cloud.9已过项没有重复修改。
