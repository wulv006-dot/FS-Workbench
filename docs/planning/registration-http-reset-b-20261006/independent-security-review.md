# B-CL-01 有限独立闭合复审

**B-CL-01关闭；本次范围未发现新的已证实阻断。可按精确两文件清单合入独立新冻结commit，并安排新版Linux43复验；不构成生产发布放行。** 审查对象是B诊断candidate-v4，不混同registration runtime-v3或旧PR5。

`candidate-v4/portal_bridge.py:30—38`先保持单一ASCII十进制/重复及TE检查，剥前导零，全零归为0，再用有效位数和字典序拒绝>4096；只有至多四位进入int。原5000零+2及header可达边界不再进入超长整数转换；非法/超限固定400，合法完整body仍405。未更改全局整数限制。

`:42—58`的单一monotonic总deadline、每次剩余预算/read1、EOF/timeout关闭及恢复原timeout保持；send/route/verify/install和真正access API认证/Origin/CSRF/会话撤销代码未被该增量改动。legacy路径仍不调用旧logout、不清cookie或撤销session。此次增量实际只改变legacy_logout的长度解析，未发现上述安全边界放松。

新增`test_http_content_length.py:78—122`是实际localhost HTTP调用Bridge的4方法/24子例：长零/零+2/65518字符字段、0/2/4096、超限大数、重复/非法/非ASCII。断言响应close、无Set-Cookie、非法长度读取次数0；server异常留存并使测试失败，未通过吞异常或放宽限制取得成功。新版慢分包记录约1.008985秒开始400并关闭，作为总deadline的保存实证。

独立核验：增量diff及原冻结→v4 diff与实际文件一致；32项完整payload的字节/SHA匹配，原31份冻结SHA匹配，30项非目标原payload不变、原测试不变。两份合入副本与清单一致：

| 精确合入文件 | SHA256 |
|---|---|
| `registration_approval_runtime_v3_20261006/portal_bridge.py`（修改，7466B） | `3b890b5edf873db7f5c73155cbf545d1d848f58d99b9a4f92a86a9eb61af38ed` |
| `registration_approval_runtime_v3_20261006/test_http_content_length.py`（新增，4985B） | `94c80e65408e84eac666c9c90ce6d76e088a25d357e18155f9ae632b82a50398` |

Windows原始日志SHA为`37b8e874511ac6eb02080517859f3ebbef8f7f7cfe2756e4217886b89eb56149`，与summary一致；独立计数43=41ok+2明确POSIXskip、0fail/error。运行记录为作者的唯一一次新版全量，本审查没有重跑、导入或执行候选，只用标准库文本/SHA/AST核验。

合入前须核实际base；清单期望`64028127dddd4b78e8ec1c0531a78c929f35c925`及原portal SHA `95e3d21deaa099cfc19df01d7d3ae9507c2377f0dbc12e5f8fd41933e41bab7f`。v3→v4增量不能直接套原PR5，应取上述两文件或完整from-frozen diff；不得复制整诊断目录。新commit/tree尚未由本轮验证。

**新版Linux43尚未通过。** 必须绑定新commit/tree、上述两SHA及32payload，原39加新4共43，两POSIX项实际执行；旧Linux39不替代。独立multiprocess四检查仍单列，不能混入本次新增4个HTTP方法。历史10054确切alias/逐包因果仍未完全证明，不因此次关闭而补造归因或抹去旧失败。

本轮未修改候选/原冻结/其他工作区，未启动HTTP、访问生产/实际cookie、上传或执行Git操作。production_ready=false保持。报告及`evidence.json`只写本任务工作区，支持工具为`D:\codex\2026-10-05\task-5\audit_registration_http_reset_b_v4.py`。
