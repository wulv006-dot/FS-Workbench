# 待批准的页面与商品源码候选

最新状态：用户明确批准后，本18文件已部署为`nav-20261109T145845Z`并逐目标读回；左侧入口独立18文件亦已部署。见[实际验收](LIVE-ACCEPTANCE.md)。下文保留部署前候选说明，业务配置仍27，未同步四个固定组合。

这是原23目标中尚未发布的17个源码目标，加重新派生的static manifest，共18目标。已上传独立stage `/opt/fs-release-stage/fc27-pages-pending-20261109`，原publisher inspect/sourceCAS/protectedCAS通过、mutations=false；未激活，等待总控取得明确的整批审批。

四个追踪源码及analytics-config已由独立 `nav-20261109T140059Z` 发布，本包不覆盖它们。它们的after SHA进入47项unchangedRequired守卫；static manifest before SHA也更新为该次实际部署值，after沿原23候选的最终110条清单，因此此次只再改变7个页面/样式/脚本条目。已启用追踪两个哈希保持。

17个源码使用 Git HEAD `89c10c630b24e9c66dc33d41fed208bde589cc70` 原字节，并逐文件确认与原23候选相同。原publisher adapter仅替换TARGETS/ROLLBACK_BASELINES/len(files)=18，原锁、fence、三服务、备份和回滚合同保持。

包：`.agent_runtime/weekly-console/page-pending-stage.tar.gz`

manifest SHA256：`d3d735a723286519e75e27bab7b1b66c17d68419fe3966b97a4d783a1737bd38`

launcher SHA256：`5c39f14f94ff20fe1284432f34bcdd5da16b1677feba230dcc20ac9c051f0615`

原23文件launch-check/launch-stage-v2仅保留历史证据，不得继续重放：其中6目标的before SHA已经不再是现役基线。未来发布仅使用重新核验并获批的独立18文件范围，业务绑定与发布版本另按批准清单执行。
