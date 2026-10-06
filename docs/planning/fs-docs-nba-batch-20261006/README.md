# 文档＋NBA receipts r4 冻结小包

本批冻结准确字节，仅供既有GitHub连接器从当前main基线建立独立draft PR。**本任务未commit/push/merge/deploy，NBA候选生产未验；releaseReady=false，无自动部署。**不混入D4、UI/auth源码；其它模块无需等NBA后续升级，本批也不等待它们生产验收才入库。

基线：bc3b29531cec2fab3fc090385f3d7d126eb9ada7。7项NBA升级（5改2增）保持规范路径；3个不变NBA测试依赖供离线小包复现，上传时无需重写其blob。API需求1.1、正式架构与产品规划、当前协作/AI流程同步；历史报告原文保留并注最新合同，验证JSON的SHA已更新。文档更新不改变角色/凭据或生产模块代码。

FC现使用既有全局账号/角色；当前观察global门户4管理员wulv/chenchao/DY/fstech，既有policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017。不是本次新增管理员。NBA源api_security仍是原3管理员模块守卫；旧C3三管理员中央源仍在main且本批不更新，不能部署覆盖四管理员现场。真实全局/模块适配留后续范围审阅，不能依文档注记认定权限代码已经修好。

独立NBA review：R3-01/R3-02只在明确候选/合成证据层可关闭；7源SHA与已审准确来源一致，未改候选。真实Linux fsync/多进程锁/掉电、浏览器Web Locks/真实登录与代理、unknown实际读回/价格效果尚未验。不得启动server/API或运行任意发布工具。只复现TEST-REPRODUCTION中已审隔离测试；该小包不需要原工程、运行数据或安装包。

上传步骤：重读main与branch SHA；如果main变化，比较完整差异并保留同事新提交，不强推。按ZIP外frozen-manifest.json只写标add/replace的路径；base tree保留其余blobs，mode100644。清单中的unchanged-dependency是复现用，不扩大变更。建立draft PR，读回commit/tree/blob大小/SHA与expectedPostTree比较；owner吴律确认NBA，root审文档与共享说明，生产动作另按精确commit范围核准。本任务没有写任何远端。

包内SOURCE-MAP保留源7项及review SHA。ZIP外manifest包含所有内容path/bytes/SHA256/Git blob/来源变换/base blob，并使用明确排序集合算法；ZIP是增量，禁止拿它整目录覆盖仓库或服务器。扫描拒绝真实秘密/配置/数据；静态扫描不是秘密不存在的证明。所有原源码、冻结C3/r4与dirty工程均保持原字节。
