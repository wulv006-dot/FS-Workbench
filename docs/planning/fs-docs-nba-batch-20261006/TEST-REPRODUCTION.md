# NBA离线测试复现

本增量ZIP保持仓库相对路径，可以直接解压到新的空临时目录运行以下5项，无需完整原工程/旧candidate目录/真实config/Cookie/数据库或pip/npm安装。10个NBA源码/测试文件已闭包：7项升级＋3项不变测试依赖。Python3.10+标准库，Node22+及其Web Crypto/AbortController为外部现有运行时；缺运行时就标未复现，不安装软件。

```powershell
python tests/integration/test_nba_receipt_durability.py
node tests/integration/test_nba_ui_receipts.cjs
node tests/integration/test_nba_bound_writer.cjs
node tests/integration/test_nba_wired_routes.cjs
node tests/integration/test_nba_pure_guards.cjs
node --check opt/nba-reprice/backend/server.js
```

这只执行已独立审阅的隔离测试：8 Python＋4 Node组（pure guards28断言），临时文件/模拟HTTP、VM/假writer，没有实际server listen、上游网络或真实写价。Python禁network/DNS/subprocess；Node VM拒网络/真实子进程。bound测试只在OS临时目录创建和清理自己文件。原review另记录12 revision3合同，不纳本小包也不宣称本轮重跑它们。Windows Linux syscall测试为mock，不是Linux真fsync/flock/掉电、真实Web Locks/账号/代理/iframe/写回验收。

完整生产运行还需安全既有sessions/environment、合适数据目录/可信持久祖先、权限与Linux锁、Python真实接口依赖及有效角色路由，未包含/未验，禁止启动server/API/ocr/fetch或部署。源p2pah_api的运行依赖和上游调用不是测试前置，隔离测试只AST提取目标函数。共享global4管理员与NBA旧3管理员模块守卫的适配待后续准确授权/审阅，不偷偷扩大本模块写权限。
