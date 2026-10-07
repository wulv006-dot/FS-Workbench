# 注册独立 multiprocess4：候选测试资料冻结范围

仅新增外部四项QA harness、原字节输入manifest、可独立复用的自检及本目录说明/有限审查/结果摘要。沿既有PR5准备，不修改32项runtime、旧冻结/审查/失败证据、共享治理或生产。新Git候选冻结不是owner确认、merge或上线批准。

runtime来源为d9dd533008fe298946eadd9e4bfea3a294aec111 / root tree d30ccde1e6551cd8ef6228a55d6629b7d603b84f / 32源子树790c5ec62472c12950e6652c5b3c4760a36df7f2。外部harness 14724B，SHA2565436f1eeb4f66977d7b88ae337a3520e1b7e90902a512425f47220a9b1b2b1bb；manifest SHA256c1c545b142cb8c5e838f71d0dcd6dbb43507f4b0f6487fcf0ecdf69ff093aa95。输入绑定见[qa-input-binding](qa-input-binding.json)。本文件不自引用包含自身的最终commit。

独立[有限复审](independent-review.md)与[evidence](evidence.json)原字节保存，关闭来源绑定、真实锁尝试/双ready和清理/禁pycache三项。报告中的本机路径是历史审查来源，不是新QA部署依赖。完整commit/root来源依赖已核远端记录；执行器仍先确认实际Git身份，再构建只含32文件的独立stage。每进程核32SHA/subtree、9模块绝对来源，子进程禁bytecode。Windows/非Linux/优化模式拒四项验收。

原自检依赖作者40blob工作文件；本次仅将fixture改为明确或仓库默认32源stage，移除开发机绝对依赖，14个test方法AST一致。新版可移植自检在Windows/Python3.14.7执行14/14、exit0、0.304s，见[结果摘要](selfcheck-result.json)。该fixture适配不是旧审查人已执行/独立审查的新测试；Popen/fcntl均为单元stub，没有候选import、真实子进程或真实锁。原14/0.204与本次14/0.304分别保留，均不抵Linux四项或43/POSIX。raw本地测试日志未纳Git。

## 从仓库运行的准确形式（先获准输入与隔离执行器）

从仓库根执行自检；默认源目录由脚本位置推导，必须是干净32文件，也可用--package提供另一个已核独立绝对stage：

```sh
python3 -B tests/registration-multiprocess-v2-20261006/test_harness_selfcheck.py --package /ABS/EXACT32_STAGE
```

四项实跑需同一已批准Linux解释器；把下列路径换成获准执行器真实绝对位置。相邻manifest、harness、selfcheck和SHA256SUMS均放QA目录；manifest不得塞进32stage。

```sh
cd /ABS/REPOSITORY/tests/registration-multiprocess-v2-20261006
sha256sum --check SHA256SUMS
/ABS/APPROVED_PYTHON -B /ABS/REPOSITORY/tests/registration-multiprocess-v2-20261006/multiprocess_probe.py /ABS/EXACT32_STAGE
```

controller创建专属合成临时根，实际同fd非阻塞flock核内核busy后继续原blocking flock，双方register就绪后共同放行；只终止/清理登记的自己子进程，正常结束还核32源前后不变。证据保留checks、每worker来源/版本及子进程退出，合成token/DB不导出。保持原四项：跨进程排斥与释放、终止自有holder后释放（SIGTERM，非断电）、同名竞争一次提交、重开schema/checkpoint一致性。不能扩述为所有native creators/任意数据损坏恢复通过。

本次Linux四项尚未执行。既有Linux3.12只能验证该宿主；Python3.9+SQLite3.53.4仍缺获准环境，不擅安装依赖。runtime43父实际结果与四项分开，不重复原同输入运行消除历史10054归因限制。

当前读取的新main为5ed20c515dc2523fc9dd532e151a3afac4c43258，其治理规则适用；PR5当前旧head仍d9dd5330/open/draft。范围只新增本两目录共9文件，不改main/shared AGENTS/HANDOFF/两活动checker清单，不修改或合并其他PR。新head需要重新评估checker、latest-main组合树与受影响owner确认；这些检查本轮没有标通过。正式合并、最终树/产物和上线仍独立批准。原被拒服务器QA上传继续取消，不用此候选作为生产传输通道，不触权限、服务或凭据。
