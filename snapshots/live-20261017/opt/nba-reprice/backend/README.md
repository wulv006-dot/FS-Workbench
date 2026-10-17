# 改价后端 · 服务器部署步骤

本目录是「NBA 2K27 自动改价控制台」的后端，已加固：凭据环境变量化、令牌鉴权、操作人审计、可移植路径。

## 依赖

- Node.js ≥ 16
- Python 3 ≥ 3.8 + `ddddocr`：`pip install ddddocr`
- 系统 `curl`

## 部署

1. 把 `backend/` 整个目录放到服务器，例如 `/opt/nba-reprice/backend/`。
2. 复制 `.env.example` 为 `.env`，填写两套账号与访问令牌：
   ```bash
   cp .env.example .env
   chmod 600 .env
   vim .env
   ```
3. 启动方式二选一：
   - 手动/pm2：`bash start.sh`
   - systemd：按 `nba-reprice.service` 里路径改好后
     ```bash
     cp nba-reprice.service /etc/systemd/system/
     systemctl daemon-reload
     systemctl enable --now nba-reprice
     ```
4. 验证：`curl http://127.0.0.1:8765/api/health`

## 前端如何接

- 前端 `frontend/index.html` 打开后，右下角「后端设置」里填：
  - 地址：后端对外地址（如 `https://backend.example.com`，反代到 8765）
  - 令牌：`.env` 里的 `ACCESS_TOKEN`（或 `OPERATORS` 中分配给该同事的 token）
- 点「保存并刷新」即可。

## 审计

- 每次改价写一行 `apply_log.jsonl`，含时间、汇率、利润率区间、三端新旧价、操作人(`operator`)。
- 建议定期备份该文件并限制目录访问权限。

## 安全提醒

- `.env` 含真实账号密码，勿提交 git、勿打包外发、勿粘贴给 AI。
- `/api/apply` 是真实改价，务必只对可信同事发放令牌，并配合 Nginx/防火墙做访问控制。
- 首次上线先用 `WRITE_READY=false` 跑通只读链路，确认无误再改为 `true`。
