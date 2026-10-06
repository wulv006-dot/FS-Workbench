# NBA revision4 持久化测试精确故障注入修复

本次只修改 `tests/integration/test_nba_receipt_durability.py`。原 revision4 313 文件及其 review/旧包保持冻结；新独立候选为 `candidate_revision4_nba_receipts_testfix1`，312 文件逐字节不变，运行源码没有修改。生产、权限、凭据、定价、Git、共享 HANDOFF/接口文档均未操作。

根线程提供的独立真实 Linux 观察：Python 3.12.14 执行 `python3 tests/integration/test_nba_receipt_durability.py`，原 8 项为 7 pass + 1 ERROR；phase=file 在 `serialized_runtime → _ensure_directory → _sync_directory → mocked os.fsync` 初始化阶段提前抛错，fake effect 未调用。原净化 ZIP SHA（由根线程提供，本任务未重新读取核验该 ZIP）：`346208ce8856c49a50564c10dd7ec2cd9f3319ba20d6e6041f9cef5b0771dabe`。这属于测试故障注入范围错误，不是观察到上游写入或本轮运行源码缺陷。

修复不跳过任何初始化 fsync：用实际 `tempfile.mkstemp` 返回的回执临时文件 fd 定位 pending 文件 fsync，其他 fd 委托原 fsync；rename 故障断言目标 ID 路径及临时 JSON 的 pending 状态；目录故障只在同 ID pending 已经 replace 到 receipts 后命中，其他同步委托原实现。三阶段都断言恰好命中一次目标故障、结果为 rejected/PENDING_PERSIST_FAILED、fake effect 调用为零、无遗留临时文件，以及只有 post-rename 目录失败保留 pending 文件。

另新增初始化 runtime 目录同步失败检查，保留并强化新 receipts 父目录同步失败检查：两者都断言故障实际命中、抛出准确 OSError、无 fake effect、无 pending 内容。初始化 OSError 冒泡至现有 CLI 后会保持绑定 unknown，既有 CLI 测试继续覆盖；pending 持久化内部 OSError 则返回 rejected。没有将所有阶段的断言改成接受任意异常。

实际执行：Windows 原生 9/9 pass；Linux 目录 syscall 分支在 Windows 的显式模拟 9/9 pass，并用原测试复现 phase=file 初始化 ERROR。模拟保留实际 `_ensure_directory/_sync_directory/_persist` 代码，只替换 Linux 目录 open/fsync/close 的宿主 syscall 适配；文件 fsync/replace 和锁仍在 Windows 实际执行。测试函数内部禁止网络/DNS/子进程，全部使用临时目录与 fake effect，不读取生产凭据。raw 输出、检查脚本和测试结果 JSON 单独保存。

本环境 WSL 未安装可用发行版，未安装或远程访问以补测。**本任务没有完成原生 Linux 重验**；Windows syscall 模拟不是 Linux 实测或掉电证明。请仓库准备线程将这个单文件补丁用于新版本第一包，保留旧包，并在此前隔离 Linux 环境重新运行上面的 Python 命令，应为 9/9 pass，才能替代旧包失败结论。Node4组及语法上轮已通过且本次文件未改，不将旧结果冒写为本轮重跑。

精确材料：`testfix.patch`、`delta.json`（新旧文件 SHA/大小）、`testfix-exact-inventory.json`（313文件新集合）、`test-results.json`、`raw-tests/`、`delivery-verification.json`、`evidence-sha256.json`。原 input inventory 和可复现脚本在本目录。集合 SHA 算法沿用 revision4：按路径排序，UTF-8 `path TAB bytes TAB sha256 LF` 后 SHA256。新包未构建/上传/推送，本交付为可供仓库准备线程替换的独立候选及补丁。
