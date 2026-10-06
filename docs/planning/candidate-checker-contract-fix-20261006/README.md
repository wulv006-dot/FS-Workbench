# 第三小候选v2：目录链接/枚举失败与执行位合同

根侧原生Linux发现v1会漏掉未列目录symlink，以及os.walk默认忽略的目录读取错误。v2保留原包，新增独立候选；不混文档/NBA v2或D4，不执行Git写、CI/Actions或生产动作。

共享树校验现在对根目录、枚举到的每个目录/文件及白名单源路径使用lstat，拒绝symlink和Windows FILE_ATTRIBUTE_REPARSE_POINT（包括junction）。先查链接，再处理根.git元数据例外，嵌套.git无例外。所有普通目录也必须是明确白名单文件或两manifest的祖先目录，未知空目录同样拒绝。os.walk(onerror=...)传播读取错误，既不跟随链接也不静默跳过不可读目录。

gitMode只承诺Git执行位，不承诺POSIX rw/owner或NTFS ACL：若行显式给出100644/100755，在POSIX逐源文件验证实际执行位；缺gitMode不添加隐含mode承诺；其他mode拒绝。Windows仅核gitMode语法，执行位未验，在--tree-only输出准确标注。ZIP条目/上传manifest的100644是构包模式声明，不等于Windows文件系统执行位已实测。根侧应用Git树后仍需读回Git blob mode。

本地Windows回归32个方法运行，无失败/错误；unittest有8个跳过条目（含symlink子例），不能称32项全部实测：2个POSIX mode方法跳过；Windows创建symlink因WinError1314未获权限，6个symlink相关跳过条目保留。没有申请额外权限/改变Developer Mode。原生Windows junction已实测3子例：未列含文件、未列空目录、已有白名单父目录，validate_tree拒绝且tree-only返回1。不可读目录以mock PermissionError核helper与真实CLI，未改真实ACL。Node失败真实CLI路径仍返回1。Linux symlink（含空、含文件、dangling、已列祖先、根.git/根目录）及chmod执行位原生负例已提供，等待根侧Linux32方法执行；Windows junction方法在Linux按平台跳过。Windows模拟不能算Linux验收。

与v1相比只改helper/checker状态说明/测试/本文及两镜像manifest。二次最小补丁checker-v1-to-v2-links.patch供已有第三draft分支采用；checker-contract-v2-links.patch是bc3至v2完整六文件补丁。禁止把bc3白名单整表覆盖其他合并增量；根侧按真实当前SHA重生双方镜像。完整业务套件本轮未重跑，仍releaseReady=false。

## v1历史说明（以下20项记录不覆盖v2新修复）

本候选独立于已冻结文档/NBA与D4包；未修改它们、原工程共享记录或业务源码。只供根协调第三draft PR，不commit/push/merge、不启用GitHub Actions/workflow/CI、不购买套餐、不碰生产。截图里的Python默认workflow不是本修复的前置。

远端基线：bc3b29531cec2fab3fc090385f3d7d126eb9ada7。两个首传manifest都明确manifestSelfExclusions为integration和provenance的UPLOAD-ALLOWLIST.json，contentFiles=321，因此完整合法树是323。旧check_candidate只补integration单一文件，要求322并拒绝合法provenance文件；汇总passed=false后也没有sys.exit非零。

本修复读取两份精确manifest并要求一致、自排除集合恰为这两个路径（不是放开provenance目录）；验证逐路径唯一/规范、行数/总字节/内容集合SHA及每个文件SHA/可用Git blob。集合SHA按清单记录的行顺序计算，首传实际为Windows pathlib排序，不改成POSIX/Unicode排序导致合法树假失败。未知文件、漂移、缺文件、非法清单均停止。只把根.git当本地checkout元数据；不再宽泛跳过__pycache__、.checks、.testdeps、.venv或任意嵌套.git。使用干净独立clone、Python -B及仓库外依赖；发现其他人的未提交文件就保留并换独立目录，不删除/重置它们。

保留原隔离业务组的代码字面量，不扩大测试/业务操作；新增--tree-only只查清单/路径/哈希，不运行候选。默认汇总失败返回1、成功0；子测试stdout即使称passed=true，只要子进程returncode非零仍失败。malformed/缺passed/字符串true都不当成功。

```powershell
python -B tests/integration/test_candidate_checker_contract.py
python -B tools/check_candidate.py --tree-only
```

20项隔离测试已过：合法323树及两自排除、Windows记录排序与Unicode重排区别、额外provenance/其他路径、旧宽泛忽略目录、缺失、同长度hash漂移、mirror不一致、多余自排除、非规范/重复路径、计数/digest错、真实CLI成功0、失败1、子进程假称成功但非零、malformed JSON和Node失败。CLI测试的所有业务/Node子命令用mock，不运行真实业务/网络/原应用。另只读核验真实已验收首传323字节树通过。

修改校验器后，它自身SHA也改变；所以随第三候选更新两份镜像清单，新增helper/隔离tests/本文的明确条目，仍自排除仅2份manifest。只修脚本却不刷新清单，会正确触发hash漂移。基于bc3的第三预期树是326（324内容＋2manifest）。

**集成注意：** 此两manifest冻结于bc3＋第三小改。前两draft PR/同事新增提交若先合入main，根协调必须用实际合并后的完整准确白名单重生两镜像的行数/字节/hash/digest，并逐项源/秘密审查；不能拿这里的bc3版本覆盖已更新manifest，不能新增宽泛忽略来让旧表通过。按最新base进行三方比较与CAS，保留NBA/D4/docs全部新blob。默认完整业务套件本轮未重跑，本修复验证的是清单与退出码合同；不以20隔离测试宣称全平台验收或生产ready。所有releaseReady=false。
