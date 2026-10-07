# Harness v2 有限静态闭合

结论：**通过，符合进入获准隔离 Linux 四项实跑的输入要求。** 上次三项建议均已闭合；本次未发现确切阻断、同进程再入锁假阳性或错误 kill 范围。此结论不是四项执行通过、runtime 重新验收或生产许可。

仅复核 `D:\codex\2026-10-06\task-9\multiprocess-harness-v2-20261006` 指定交付及理解锁调用所必需的冻结源码片段。未执行/导入 harness、selfcheck 或候选代码，未安装、传输、部署、SSH、访问生产或真实 cookie，未改原 harness、runtime32、其他工作区或共享治理。独立 Python 标准库工具只读取文本/JSON，计算哈希、Git 对象及 AST；交付写入本审核工作区。

## 冻结身份与证据

`multiprocess_probe.py` 为 14,724 字节，SHA256 `5436f1eeb4f66977d7b88ae337a3520e1b7e90902a512425f47220a9b1b2b1bb`。

| 身份 | 值 |
| --- | --- |
| 完整 commit | `d9dd533008fe298946eadd9e4bfea3a294aec111` |
| root tree | `d30ccde1e6551cd8ef6228a55d6629b7d603b84f` |
| 32 文件 source subtree | `790c5ec62472c12950e6652c5b3c4760a36df7f2` |
| 相邻 manifest SHA256 | `c1c545b142cb8c5e838f71d0dcd6dbb43507f4b0f6487fcf0ecdf69ff093aa95` |

独立复算32份保存 readback 字节的 size/SHA256/Git blob，全部匹配 manifest、保存的 Git tree 和本地 B-v4 对应32文件；保存的递归 Git tree 元数据自底向上复算匹配上述 root/subtree，commit 记录所指 root 一致。32文件自身只能证明 source subtree，完整 commit 的来源仍依赖保存的远端记录；本次没有实时验证远端身份，也没有取回其他 root blob 内容。manifest 中 `baseline_commit/tree` 是历史基线，当前身份由 harness 常量及上述保存记录绑定，没有将其误当当前 commit。

原 harness 当前 SHA256 仍为 `9baade1b8b8163c41b3bbb387ca6425b580b7190cbbdedf666988f87a7d16955`；交付 diff 与两端文本的独立统一 diff 完全一致。源码及自检文件均通过 Python3.9 AST 解析。作者日志记录14/14、0.204秒、OK，与14个测试定义对应；这是保存日志核对，审核人没有重跑测试，fcntl/Popen stub 不证明真实多进程结果。详见 [evidence.json](evidence.json)。

## 三项闭合与专门问题

以下行号均来自本次冻结 `multiprocess_probe.py`；runtime 行号仅用于锁调用必要上下文，不构成扩展重审。

| 检查 | 文件/行与已证实证据 | 影响及闭合结论 |
| --- | --- | --- |
| 输入及实际 import 来源 | harness 16–26 固定身份及9模块；53–92 核 manifest 原字节、32 size/SHA、非链接、无额外文件/cache并复算子树；94–114 核实际 `__file__`、拒预加载；worker 220–224 每子进程写来源 receipt；300–307 收集 controller/七个 worker 来源；315–316 结束再核源码 | 上次未绑定输入的问题闭合。不是仅写常量标签；实际32字节和9个候选模块来源都有校验。常量 commit/root 仍需新 QA 独立确认 Git 来源。 |
| 真实锁尝试与 ready 屏障 | harness 182–211 在真实相同 fd 上核 dev/inode，实际 `LOCK_EX|LOCK_NB` 只有 EAGAIN/EACCES 才写 kernel-blocked，随后原 blocking flock；229–234 observer 覆盖 contender 初次 build；271–280 父进程等该握手后才释放 holder；246–247 register 在 build 后报 ready；293–296 等双 ready且两进程活着才发 start | 上次固定延时、加载前即释放 race 的证据不足闭合。没有用 sleep 长度声称竞争成立，短 sleep 仅用于有界文件轮询。双 ready 证明双方已加载并等待共同释放，不能保证调度器在同一瞬间执行注册；四项的结论仍以真实运行断言为限。 |
| 即时登记、清理和禁 pycache | harness 149–154 每次成功 Popen 后立即登记，包括 prepare；156–179 有界 communicate/terminate/kill逐个清理已登记对象；291–292 第二次启动失败时 first 已登记；2–3 首次导入前禁 bytecode，137–142 子环境去 Python 注入/优化变量并设禁 bytecode，150 显式 `-B`；315–316 源后校验 | 上次漏 first 和生成源码 cache 的问题闭合。prepare 也纳入 finally 清理；清理失败会把结果设为 failed。 |

**同进程再入锁：没有发现所问假阳性。** `candidate-v4/vendor/native_integration.py:40–69` 的 fence 在线程 depth 非零时只嵌套 yield；首次 OS lock 成功后才将 depth 设为1，finally 复位并关闭 fd。`candidate-v4/runtime.py:61,69–72,139` 表明 build 创建全新 Namespace，构造的首次外层 fence 尚无同进程已持锁 fd；内部 connection 复用 depth，不再次 flock。因此 harness 229–234 的首次真实 busy 握手是在独立 contender 进程的首次 OS 获取处，不会把同进程另开 fd 自锁误记成 holder 排斥。后续显式 fence/connection 的嵌套也不会产生该自锁。本结论来自静态控制流，未执行真实 flock。

**kill 范围：没有发现错误目标。** harness 151 用参数数组启动自身 worker，无 shell；153 立即存储其 Popen 对象。165/169 只对这个登记对象 terminate/kill；286 只终止当前由 start 返回的 hold-2 对象。没有进程枚举、全局 PID、进程组或系统服务 kill。七个 phase 都在专用 TemporaryDirectory 中工作。第二项是终止自有 holder 后的内核锁释放，不能扩称断电/全存储恢复。

本次没有新的缺陷项或强制修法；不需要为静态闭合再改 harness 或32源码。

## 实跑必要输入及验收边界

1. 在获准隔离 Linux 执行器上，独立核验上述完整 commit、root tree、source subtree 和取得的源码来源；新建非链接绝对 stage，只放 manifest 指定32文件。不得把整个40-blob工作资料、Git元数据、manifest或cache混进源码 stage。
2. 独立 harness 目录放本次冻结 `multiprocess_probe.py`、相邻 `runtime-test-manifest.json` 和 `SHA256SUMS`；先按两项冻结哈希核验。stage 和 harness 目录分开，不复用未获准传输/服务器路径。
3. 使用获准 Linux、启用 assertions 的绝对 Python 解释器，显式 `-B`；具备标准库 fcntl/sqlite3、可用非链接的私人临时目录。明确记录 Python/SQLite 版本及获准 loader 环境，子进程继承同环境。宿主3.12结果不能替代尚未执行的私人3.9+SQLite3.53.4组合。
4. 实际输出须 exit0、status=passed、四个检查全部出现、七个自有 worker 收尾、controller/child模块来源均指向新stage且源前后未变。保留原始输出和输入/解释器哈希；失败不得算通过。

未来准确命令形式：`/ABS/APPROVED_PYTHON -B /ABS/HARNESS_DIRECTORY/multiprocess_probe.py /ABS/EXACT32_STAGE`。本次未调用。

四项范围是跨进程排斥及释放、终止自有 holder 后释放、同名竞争单次提交、重开连接的 schema/checkpoint 一致性。**尚未执行的 Linux 四项仍待实跑；14项自检、静态通过均不抵四项或43/POSIX。** 未覆盖所有 native creators、完整异常恢复、真实身份/cookie、Nginx、部署或生产运行，未恢复旧 publisher 链，也未扩展重审已冻结 runtime。
