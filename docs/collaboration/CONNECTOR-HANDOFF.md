# 现有GitHub连接器写入口核查（只读能力核查；未试写）

可调用create_blob(content,encoding=utf-8/base64)、create_tree(tree_elements,可选base_tree_sha)、create_commit(tree_sha,parent_sha必填字符串)、update_ref(branch_name,sha,force=false)。create_file可通过Contents API创建UTF-8文件；该工具说明不创建新branch。既有连接wulv006-dot能读此private库并返回admin/push，大超write，未新认证。

空库特殊限制必须由根核对：create_commit包装参数不能表达原生API空parents数组；不要用空字符串/零SHA猜parent。GitHub官方说明empty库（无branch）不能通过Git refs API创建新ref，即使commit SHA已存在。因此当前不能宣称四个工具直接完成空库根提交的写入口已验收。官方文档：https://docs.github.com/en/rest/git/refs#create-a-reference 与 https://docs.github.com/en/rest/git/commits#create-a-commit 。

可供根选择的推荐路径：先在已授权白名单内，用已核实的Contents创建入口只bootstrap本清单README.md到默认main，读取所得真实commit和branch；随后上传本清单各blob（PNG base64，其余UTF-8/bytes一致）并用空base创建完整精确tree，commit父节点用真实bootstrap SHA，最后在根复核最新main不变后force=false更新ref。此过程是一个明确的干净README引导commit＋完整首包commit；对象创建并非发布，只有完整tree ref更新才宣称全首包入库成功。创建README在empty库是否受该包装支持尚未调用验证，根必须确认可行后执行；不新OAuth/token、不直接curl凭据。

若root要求一次single-root-commit或Contents包装在空库不可用，则本入口不能满足；使用其它已授权既有连接支持的bootstrap/Git路径，或保持准备完成。不要初始化原E Git、复制旧历史或逐文件commit数百次规避原子首包review。ZIP内仅最终白名单，用外部final-target-inventory完整核对树和SHA。

远端有新提交时暂停empty方案，clone/fetch或读真实tree作差异，不reset/forcepush。update_ref force=false仍不是完整compare-and-swap，更新前后查sha，意外并发必须报告；权限或写结果须以实际工具和读回为准。
