// 本机没有 npm / Playwright 自带 Chromium 时，用本机 Chrome 跑活动页的浏览器测试。
//
// 用法：
//   1. 在 scratchpad 里建 shim/node_modules/playwright/index.js，内容就是本文件（改好下面两个路径）。
//   2. 运行测试时设 NODE_PATH=<scratchpad>/shim/node_modules，测试里的 require('playwright') 就会走这里：
//        NODE_PATH="<scratchpad>/shim/node_modules" \
//          D:/codex/FC27/tools/colbymchenry-codegraph/1.6.2/codegraph-win32-x64/node.exe --test tests/xxx.test.cjs
//   `*-browser.cjs` 脚本不带 --test，直接用 node 跑。
//
// 路径是本机相关的，机器变了先核对：
const PLAYWRIGHT_PKG = 'D:/codex/FC27/tools/playwright-mcp/node_modules/.pnpm/playwright@1.66.0-alpha-2026-11-09/node_modules/playwright';
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const real = require(PLAYWRIGHT_PKG);
const chromium = real.chromium;
const launch = chromium.launch.bind(chromium);
chromium.launch = (options = {}) => launch({ ...options, executablePath: CHROME });
module.exports = { ...real, chromium };
