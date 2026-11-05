# FS 导航体验改造 · 2026-11-03

## 结果

统一静态页面与动态页面的导航增强，支持分组互斥展开、独立收起按钮、跨页状态记忆、工具搜索、Ctrl K、72px 紧凑侧栏、手机抽屉与键盘操作。添加原生跨文档过渡，尊重减少动态效果偏好。使用原有深浅主题。保留正常链接、新标签页、前进后退与每个模块原有服务端门禁。

活动分析页面重复的 224px 左侧留白已修复。首页业务脚本重新生成工作区卡片后，会消失的活动入口和旧 Hermes 目的地址由同一导航清单校正，补齐营销入口。移除旧导航对整个业务工作区的推测性预渲染，不提前启动业务页面。

## 原问题与证据

- 分组标题只有跳转链接，没有展开/收起控件，多个分组常驻展开。
- 静态 nav.js 与动态 hubnav.js 使用不同渲染逻辑。后者在发现静态导航后直接退出。
- /__hub/ 脚本缓存30天，静态入口、独立模块和服务器注入使用不同历史版本号。
- 数据看板、数据工具、客单追踪和任务台各自抑制统一注入，需要按真实路由补齐。
- 活动分析 main 的 margin-left 为224px，同时 body 已预留导航宽度，形成双重留白。修改后 main 左边界248px、margin-left为0。
- 首页原有经营指标取数失败、G2G入口502、团队工具目录403。均保留真实错误，未通过UI修复伪造可用状态，也未恢复暂停服务。

## 验证范围

已逐一打开导航中38个非权限管理入口；36个返回业务页面，G2G与团队工具目录分别返回502/403。检查导航版本和重复导航元素，异步模块单独等待并复查。未执行改价、采集、参数保存、任务派发或机器人消息。

真实界面验收包括分组展开互斥、搜索匹配与空结果、72px紧凑模式与正文对齐、跨页和刷新记忆、Ctrl K从紧凑模式打开并聚焦搜索、深浅主题。390px手机抽屉已做本地验收；桌面各入口的加载瞬间横向溢出不能据此认定为稳定布局故障，抽查球类工作区和NBA稳定后无横向溢出。未做每个业务模块自身的数据正确性、所有手机正文布局或量化性能基准测试。

Node语法检查通过。UI交互验证由浏览器实际操作完成；静态检查不能代替业务验收。浏览器原生过渡能力不支持时保留普通导航。模块自身接口取数时间仍然存在，不承诺所有模块零等待。

## 活动源与发布

2026-11-05 SEO注册修复：`build.cjs <现役navigation.json>`显式使用当前清单，避免增强导航用历史内嵌清单覆盖新增项。`prepare-current.cjs <16文件捕获目录> <捕获manifest> <现役navigation.json> <新输出目录>`核固定16目标和捕获SHA，确认现役脚本与维护源逻辑一致后，仅替换两脚本的registry常量与14个消费者的导航缓存引用，保留其余字节。输入不符即停止；不覆盖他人修改。它只制作候选，发布仍使用已核SHA的现役原publisher、双锁、CAS、备份、Nginx检查和reload；不新增发布器或操作业务worker/timer。

可编辑增强源：navigation-experience.js、navigation-experience.css。build.cjs将增强代码编译到已读取线上基线hubnav.live.js和nav.live.js后。基线为本批历史输入，后续发布必须重新核对当前线上基线，不直接重放。

服务器目标：/var/www/hub/hubnav.js、nav.js、navigation-experience.css；11个静态入口仅更新版本/样式引用；主站及formal路由仅更新导航资源注入。复用现有release_ui_finish发布器、共享锁、逐文件CAS、备份与回滚。没有修改业务数据库、定价参数、权限、采集、writer或定时任务。

最终版本引用：navigation-experience-20261103-v2。

发布档案：D:\共享资源\服务器\2026-11-03_FS导航体验改造。
代码工作分支：codex/navigation-experience-20261103。

## 回滚

按发布逆序回滚，每步使用同批release_ui.py、原manifest SHA和对应备份目录。先核对线上文件没有其他人后续修改；CAS不匹配时停止，不能用整个旧目录覆盖。

1. final-v2：manifest 11399199bee4370524e8ff4df6a6669c380801810eb5980e8b647d3ecb8e0f29，备份 /var/backups/fs-navigation-20261006/nav-20261103T070300Z。
2. entry-fix：manifest 4c165a31d4968680bc8ea47586fe29461a8201c29188daab438f66f15dedb02e，备份 /var/backups/fs-navigation-20261006/nav-20261103T070200Z。
3. static-v1：manifest d71405565d8110f69a5ef4525197fd3dbe857ded9a2b72e02d75b1f88b90d4ac，备份 /var/backups/fs-navigation-20261006/nav-20261103T070100Z。
4. v1：manifest 5bafa6f6b84de10bff9f373d9828fcb0b75a85ead97f89f273ae0286d5b2a210，备份 /var/backups/fs-navigation-20261006/nav-20261103T070000Z。

对应暂存目录均位于 /opt/fs-release-stage/navigation-experience-20261103-*。回滚命令格式为 python3 release_ui.py rollback <该批备份目录> <该批manifest SHA>。回滚后由原发布器检查并reload Nginx，真实入口复验。新CSS文件可保留为无引用资产，不手工删除。

设计参考：已读取 GitHub anthropics/skills 的 frontend-design/SKILL.md，采用明确层级、响应用户动作的适量动画、可访问性和减少动态效果原则；未安装外部运行代码或引入外部CDN依赖。
