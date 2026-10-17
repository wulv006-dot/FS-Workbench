# AI 适配独立只读审计

结论：未发现本次官方adapter接线、旧供应商退役或发布边界需要修复的阻塞问题。可进入主线最终组合Linux验证；本记录不是部署、provider真实调用或自然周期验收。

审计范围为四个新候选及它们的现有消费者，按同一个共享provider锁内一次请求的实际运行规模核对。没有修改主线AI业务文件或冻结publisher。2026-10-15 02:20–02:24北京时间只读现场证据保存在 `live-ai-callgraph-and-timers.json`、`linux-existing-import-readback.json`、`live-nightly-metadata.json`、`live-provider-permissions.json`。

| 新候选输入 | SHA-256 |
| --- | --- |
| `workspace_official_model.py` | `dd50a42f3044a39ac11e1010a2d089c88055bdd1ce52cde19a4c033ef8587d7a` |
| `boss_daily.py` | `9b102d43b11792e72e374af46819b2904b84b061a4da712ed4c44bc86048a8d1` |
| `management_daily.py` | `3547bef9ddf3e9084f143971c8cad8629f8d4800f64f2abd48fe5dcaff50a121` |
| `game_intelligence.py` | `96a0719e371c2b2844fb47dcf238cbd51e4b6c13947142444d240a1b4a16937b` |

这些输入在本目录相对路径 `../../ai/candidate`；表仅固定审计输入身份，搬到私库后由最终SOURCE-MAP核对。若后续业务源变化，重核受影响部分。

工作区任务的入口是真实 `/opt/fs-boss-workspaces/backend/boss_daily.py`；systemd给定WorkingDirectory=/opt/fs-boss-workspaces及PYTHONPATH=/opt/fs-exact-range-20261001。脚本目录可找到新workspace_official_model及两消费者，adapter追加 `/opt/fs-hermes-fc`，随后复用direct_provider和proxy_gateway.schemas。已有LinuxPython3.9.18已成功导入fc_daily、direct_provider、proxy_gateway、nightly_http和两消费者，HTTPS/_ssl可用，当前schemas为15项。当前direct_provider SHA `9ac9e09238f0c934ca6977a3af02df58f3a9185d8f0b9668f56d0fd4c7a55fed`与已审活动源码相同。

新adapter没有新credential/provider/ledger：同DailyReports、同fc-daily目录与provider.lock；指纹加入官方policy，避免拿旧供应商回执当新供应商结果。请求使用deepseek-flash、high、官方393216输出上限、tools=[]；现有provider负责流式usage与deadline。原5000/6000调用参数不压低官方输出上限。未知结果原样返回、没有请求重试；诊断移除reasoning_content，保留公开输出/usage。两消费者的模型身份及usage检查转入同adapter。

现场两个boss服务的User/Group均root，准确区间服务User=root且PID32743的实际UID/GID均0。现有key仅做stat：root:root0600普通非symlink文件，secrets及fs父目录root0700，祖先可由root遍历；与direct_provider的文件属主、模式、大小检查相容。未读取key正文、hash或格式，没有发起provider调用；密钥合法性/供应商接受不由此证明。

旧深度调用链已核实际文件：range_api→fc_deep_service→fc_deep_model.explain→ai_advisor_model.request_model。活动fc_deep_model SHA `15965d1d331444635dd8ef677cacb2f05d2e21fa6c33ff6ae7bf53315b76b067`与本地fact_fix source一致。实际fc_deep_analysis.py只提供证据计算，无独立模型出口；没有假设不存在的fc_deep.py。新ai_advisor_model的request_model/explain直接返回retired，fc_daily_model.configured=false/explain直接retired，旧日报/Advisor的enqueue/start/tick/run_one也退役，因此间接深度入口不会发旧Bailian请求。旧ENDPOINT文本保留为历史常量，不构成可执行请求出口。

现场启用的准备timer为game00:05、marketing00:10、management00:20，均active/enabled、Persistent=false、无drop-in改写；旧weekly timer inactive/disabled。服务器localtime实际指向Asia/Shanghai且当前+0800；旧systemd不支持的timedatectl字段留null，不以该null冒充UTC。Hermes内部nightly配置已启用，上海daily00:45、Monday weekly01:45、月首monthly03:15，截止06:59且07:00前保存终止状态。boss新候选使用06:59 POSIX alarm、采集/网络deadline及模型/发布前deadline；marketing现有scheduled入口也明确00:10–06:59及子进程timeout。手动调查保持原授权入口，不是后台补跑。

原FC代码仍有9:15历史常量，但start/tick/生成入口已退役，status返回enabled=false、time/next_run=null，不会启动上午旧分析。两boss service的failed/PID0是原00:59失败历史；本次未reset-failed或重跑。

发布guard按现场36条目标/祖先/共享锁 metadata检查：20目标祖先无symlink、root:root且无group/world写；只读新增文件缺失身份与7新目标清单吻合。`/var/lib/fs-hermes-fc`root:9876/0750不在目标祖先链，原approved_daily_group不需扩权；provider/admission FD边界仍适用。冻结AI20 publisher只reload单位与重启range，cleanup保持inactive，worker无改动/无需重启。

主线package_release.py与当前private-candidate已包含三处相对路径替换及脱敏fixture，消除了独立私库QA对E工程旧文件夹的依赖；该核对未执行或改写包装脚本。新的最终组合Linux测试、实际provider输出和自然周期仍未验证。
