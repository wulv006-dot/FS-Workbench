> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# 发布前仅两项明确决定

1. FC-only旧页面依赖四精确静态资源：`/dashboard/fs-home/transactions/business-theme.css`、`business-theme.js`、`business-range.js`、`exact-range-client.js`。归档FC门禁合同只确定`/s/wulv/fc27-ops/`和`/tools/fc27-players/`，旧不受限fallback确有内部扩权，不能据它恢复全部dashboard访问。当前候选仅原FC路径可读，四内部引用仍拒绝，故FC-only页面完整兼容未通过。需父向用户确认：允许将这四无秘密的前端资源映射为FC专用只读别名并调整FC页面引用吗？建议用FC别名、继续拒绝所有内部经营JSON/页面；此轮没有改核心FC HTML SHA或nginx。另一方案是已有内部登记者用门户登录；不能以它冒充外部FC兼容。
2. NBA候选revision2逐轮`window.confirm`与原无人值守循环不等价。方案A：管理员逐计划确认，取消即停，不称无人值守。方案B：批准明确自动策略/限额/平台/有效期和服务器执行身份，一次批准策略、逐循环绑定计划/hash/receipt，未知暂停需人工核对；须另业务授权、另实施/运行验收。两方案都保持缺身份拒绝、默认写关闭、管理员/POST/正价/Origin守卫。revision3没有自行选择，不更改真实生产自动规则。

运行共同门槛：真实登录与有效路由/单位、Linux多进程锁、NBA/MLB既有认证接入、FS发布网关、真实FC外部与内部隔离等仍需后续受控验收。无可用真实只读账户，不新建或降级管理员补测。各OPEN保留，不以本轮代码/模拟通过关闭生产OD。
