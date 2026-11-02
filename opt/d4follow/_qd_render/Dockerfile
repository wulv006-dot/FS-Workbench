# 千岛抓取「渲染后端」镜像
#
# 背景：生产机 CentOS 7.9（glibc 2.17）跑不了 Playwright（要求 glibc >= 2.27），
#       于是把浏览器这一段放进容器。容器内只暴露 HTTP，宿主机不碰浏览器。
#
# 基础镜像 mcr.microsoft.com/playwright/python:v1.47.0-jammy 自带 Chromium
# （/ms-playwright/chromium-1134，正是 playwright 1.47.0 的配套版本），
# 但实测其 Python 环境里**没有 playwright 包**（pip list 为空），所以这里补装同版本，
# 保证 Python 包版本与已下载的浏览器版本严格对齐（错版本会导致 executable doesn't exist）。
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

RUN pip install --no-cache-dir playwright==1.47.0 \
 && python -c "import importlib.metadata as m, sys; print('[build] playwright', m.version('playwright'), 'on python', sys.version.split()[0]); from playwright.sync_api import sync_playwright; print('[build] sync_api 可用')"
