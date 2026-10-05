> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# FC外置状态迁移前置合同

本文件不改全球新环境默认，不生成/导入真实策略或价格；tools/fc_migration_contract.py只做内存校验。已有运行意图由用户批准rev25：降幅范围6–8/5–6/0–5/0–0；schedule_revision23、Coins ON/60min/10%，Players/Gallery其它既有参数保持外置原样，Gallery用户OFF且原600分钟周期不变。本轮不运行迁移或变更调度。

必须在既有受支持保密流程取得当前策略修订号和已批准数量向量，数量白名单不是从示例猜出：每个平台15项，20/30/40K不得回归；vector保持gold/discount/give及其顺序相同。缺配置或revision冲突拒绝迁移；初始revision0/system off的通用默认不能宣称是rev25。测试中50–190K只是合成向量，不是生产档位。

六后台映射来自coin_all_sync_job.PRODUCTS：PS ALL163329309/MMOEXP163329311/aid21587；XBOX ALL163329275/MMOEXP163329277/aid21585；PC ALL163329343/MMOEXP163329345/aid21589。mid41217957/gid1327/cid9623；ALLsite0/MMOEXPsite266。现有源→ALL只复制已确认price，不计算、不删档或恢复18项。

验收分层：只读校验六行与批准15向量；现有writer状态/双确认/锁和unknown不重试仍独立；再核对三公开PS/XBOX/PC每项gold/discount/give与来源，不能只以数组长度或样本价通过。真实数量向量、六行/三公开页与当前修订未在本轮读取，故只标合同/合成通过。

原定价：Lootbar售价/(基础+赠送)×我方基础×既有降幅；我方赠送计成本；Xbox跟PS且独立成本门槛。保留v7、Aion2与FC原生订单口径，不以D4竞价替代经营数据。后续执行迁移仍需具体受控备份/现场SHA/原子状态及回滚，不凭本候选部署。

后续增量：本机13:35巡检归档的13:45只读tiers证据现已提取仅数量向量（config/examples/fc-approved-tier-quantities.reference.json，三平台各15项、六行ALL/source数量一致），未复制实际价格、角色、会话或订单，未新发生产请求。它是带日期/SHA的参考，不是自动恢复表；迁移仍须当前读回与修订核对。新增第五合成用例使用该真实数量向量配合假价格，验证只读保留，不冒充实时运行验收。

revision3补强：tools工具现逐字段校验六商品身份，数量向量有限正Decimal且数值唯一并保序。test_fc_rev25_matrix.py用16合成输入直比当前Python/JS并调用check_write，六测试覆盖四档与篡改；未读真实价格或迁移策略。
