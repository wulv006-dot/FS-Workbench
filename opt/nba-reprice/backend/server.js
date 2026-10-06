/**
 * NBA 2K27 自动改价 - 本地后端服务
 *
 * 职责：
 *  1. 后端自动登录 order.p2pah.cn（读取采购价时触发，含验证码自动识别，前端无感）
 *  2. 读取发货记录，解析 NBA 2K27 (gid=1306) 的 1 Game Coins (cid=1) 最新采购单价
 *  3. 返回 JSON 给前端控制台
 *
 * 依赖：Python 环境的 ddddocr（用于验证码识别）
 */
const http = require('http');
const https = require('https');
const { execFile } = require('child_process');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

// 解析 OPERATORS 环境变量（{"token":"名字"}），用于多人身份与审计
function loadOperators() {
  const raw = process.env.OPERATORS || '';
  if (!raw) return {};
  try {
    const o = JSON.parse(raw);
    return (o && typeof o === 'object' && !Array.isArray(o)) ? o : {};
  } catch (e) {
    console.error('[warn] OPERATORS 环境变量不是合法 JSON，已忽略：', e.message);
    return {};
  }
}

// 从请求头解析 token，返回归属名；无 token 或非法返回 null
function resolveOperator(req) {
  const h = String(req.headers['authorization'] || '');
  let tok = '';
  if (h.toLowerCase().startsWith('bearer ')) tok = h.slice(7).trim();
  if (!tok) tok = String(req.headers['x-access-token'] || '').trim();
  if (!tok) return null;
  if (Object.prototype.hasOwnProperty.call(OPERATORS, tok)) return OPERATORS[tok];
  if (ACCESS_TOKEN && tok === ACCESS_TOKEN) return OPERATOR_NAME;
  return null;
}

const PORT = Number(process.env.PORT || 8765);
// 2026-09-30 部署到 FS 平台：BIND_HOST=127.0.0.1 时只允许本机 nginx 反代访问，
// 对外一律走 https://47.85.224.112/nba2k27/（统一登录保护），8765 不暴露公网。
const BIND_HOST = process.env.BIND_HOST || '0.0.0.0';

// ===== 配置（凭据一律从环境变量读取，禁止写入代码 / 提交 / 打包）=====
const BASE = 'https://order.p2pah.cn';
const USERNAME = process.env.P2PAH_ORDER_USERNAME || '';
const PASSWORD = process.env.P2PAH_ORDER_PASSWORD || '';
const GID = 1306;   // 1306 NBA 2K27
const CID = 1;      // 1 Game Coins
const RATE = Number(process.env.RATE || 6.65);  // 汇率 ¥/$

const PYTHON = process.env.PYTHON || (process.platform === 'win32' ? 'python.exe' : 'python3');
const OCR_SCRIPT = path.join(__dirname, 'ocr_captcha.py');

// ===== 访问鉴权 =====
const ACCESS_TOKEN = process.env.ACCESS_TOKEN || '';          // 单一口令（可选；为空则 AUTH 不启用，仅回环可用）
const OPERATOR_NAME = process.env.OPERATOR_NAME || 'shared';  // 用 ACCESS_TOKEN 操作时记在审计日志里的归属名
const OPERATORS = loadOperators();                            // 可选 {"token":"名字"} 多人身份映射
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN || '';      // 可选，CORS 白名单（逗号分隔）
const AUTH_ENABLED = !!(ACCESS_TOKEN || Object.keys(OPERATORS).length);

// 工作目录
const WORK_DIR = __dirname;
const COOKIE_FILE = path.join(WORK_DIR, '.cookies.txt');

// ===== 登录态 =====
let session = {
  loggedIn: false,
  cookie: '',          // 当前 cookie 字符串
  loginAt: 0,          // 登录时间戳
};

// ===== 工具：HTTP 请求（带 cookie 管理） =====
function request(method, urlPath, { headers = {}, body = null, redirects = 0 } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath);
    const isHttps = url.protocol === 'https:';
    const mod = isHttps ? https : http;
    const hdrs = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Referer': BASE + '/login.html',
      'Origin': BASE,
      ...headers,
    };
    if (session.cookie) hdrs['Cookie'] = session.cookie;
    if (body && !hdrs['Content-Type']) {
      hdrs['Content-Type'] = 'application/x-www-form-urlencoded';
    }

    const req = mod.request(url, { method, headers: hdrs }, (res) => {
      // 收集 set-cookie
      const setCookies = res.headers['set-cookie'];
      if (setCookies) {
        for (const sc of setCookies) {
          const kv = sc.split(';')[0];
          const [k, v] = kv.split('=');
          updateCookie(k, v);
        }
      }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        const buf = Buffer.concat(chunks);
        const result = {
          status: res.statusCode,
          headers: res.headers,
          body: buf,
          text: buf.toString('utf8'),
        };
        // 处理重定向
        if ([301, 302, 303, 307].includes(res.statusCode) && res.headers.location && redirects < 5) {
          const loc = res.headers.location;
          const nextUrl = loc.startsWith('http') ? loc : BASE + loc;
          return resolve(request(method, nextUrl, { headers, body, redirects: redirects + 1 }));
        }
        resolve(result);
      });
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

function updateCookie(key, value) {
  if (!session.cookie) {
    session.cookie = `${key}=${value}`;
    return;
  }
  const parts = session.cookie.split('; ').filter((p) => !p.startsWith(key + '='));
  parts.push(`${key}=${value}`);
  session.cookie = parts.join('; ');
}

function persistCookie() {
  fs.writeFileSync(COOKIE_FILE, session.cookie || '', 'utf8');
}

function loadCookie() {
  if (fs.existsSync(COOKIE_FILE)) {
    session.cookie = fs.readFileSync(COOKIE_FILE, 'utf8').trim();
  }
}

// ===== 验证码识别 =====
function ocrCaptcha(imageBuffer) {
  return new Promise((resolve, reject) => {
    const tmpFile = path.join(WORK_DIR, '.captcha_tmp.png');
    fs.writeFileSync(tmpFile, imageBuffer);
    execFile(PYTHON, [OCR_SCRIPT, tmpFile], { timeout: 30000 }, (err, stdout, stderr) => {
      if (err) return reject(new Error('OCR failed: ' + (stderr || err.message)));
      resolve(stdout.trim());
    });
  });
}

// ===== 登录（后端自动登录，读取采购价时由 ensureLogin 触发，前端无感）=====
async function login() {
  // 先访问登录页，让服务器分配真实 PHPSESSID（不带旧 cookie，强制新 session）
  session.cookie = '';
  const initRes = await request('GET', `${BASE}/login.html`);
  if (!session.cookie.includes('PHPSESSID')) {
    throw new Error('无法获取 PHPSESSID');
  }

  const maxTry = 5;
  for (let attempt = 1; attempt <= maxTry; attempt++) {
    // 1. 下载验证码（会生成新验证码并写入 session）
    const capRes = await request('GET', `${BASE}/new_captcha.html?height=32&width=150&font_size=18`);
    if (capRes.status !== 200) throw new Error('验证码下载失败: HTTP ' + capRes.status);

    // 2. OCR 识别
    const captcha = await ocrCaptcha(capRes.body);
    if (!captcha || captcha.length < 3) {
      console.log(`  [登录] 第${attempt}次 OCR 结果异常: "${captcha}"，重试`);
      continue;
    }
    console.log(`  [登录] 第${attempt}次，验证码识别为: ${captcha}`);

    // 3. 提交登录
    const body = `username=${encodeURIComponent(USERNAME)}&password=${encodeURIComponent(PASSWORD)}&captcha=${encodeURIComponent(captcha)}&redirect=`;
    const loginRes = await request('POST', `${BASE}/admin/public/dologin.html`, { body });
    const txt = loginRes.text;
    if (txt.includes('登录成功')) {
      session.loggedIn = true;
      session.loginAt = Date.now();
      persistCookie();
      console.log('  [登录] 成功');
      return true;
    }
    console.log(`  [登录] 第${attempt}次失败（响应非成功），重试...`);
  }
  throw new Error('登录失败：验证码识别多次未成功');
}

// 判断是否已登录（用 cookie 探测）
async function ensureLogin() {
  if (session.loggedIn && (Date.now() - session.loginAt) < 30 * 60 * 1000) {
    return true;
  }
  // 尝试用现有 cookie 探测
  if (session.cookie) {
    const probe = await request('GET', `${BASE}/order/admin_delivery/index.html?gid=${GID}&cid=${CID}`);
    if (!probe.text.includes('用户名或邮箱')) {
      session.loggedIn = true;
      session.loginAt = Date.now();
      return true;
    }
  }
  return login();
}

// ===== 读取发货记录并解析最新采购单价 =====
// 旧后台（order.p2pah.cn）的游戏区 aid → 平台名（来自列表 title="1306 ▶aid"）
const AREA_BY_AID = { 21764: 'PS', 21766: 'Xbox', 21768: 'PC' };

function parseDeliveryPrice(html) {
  // 每行 <tr data-id=...>；行内 <td> 两种形态：
  //   新单（可编辑）: <td class="toggle-input" data-type="qty|delivery_price" ...><input value="..">
  //   老单（只读）  : <td title="" data-toggle="tooltip">0.400000</td>   ← 无 input
  // 两种形态列序一致：平台格(title="gid ▶aid") 后 +1=数量、+2=赠送、+3=采购单价
  const rowRe = /<tr\s+data-id="(\d+)"[^>]*>([\s\S]*?)<\/tr>/g;
  const cellRe = /<td\b([^>]*)>([\s\S]*?)(?=<td\b|<\/tr>|$)/g;
  const strip = (s) => String(s).replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
  const rows = [];
  let m;
  while ((m = rowRe.exec(html)) !== null) {
    const id = m[1];
    const seg = m[2];
    const cells = [];
    let c;
    cellRe.lastIndex = 0;
    while ((c = cellRe.exec(seg)) !== null) {
      const attrs = c[1] || '';
      const inner = c[2] || '';
      const dt = (attrs.match(/data-type="([^"]+)"/) || [])[1] || '';
      const cls = (attrs.match(/class="([^"]+)"/) || [])[1] || '';
      const title = (attrs.match(/title="([^"]*)"/) || [])[1] || '';
      const val = (inner.match(/value="([^"]*)"/) || [])[1] || '';
      cells.push({ type: dt, cls, title, text: strip(inner), value: val });
    }
    // 平台格：title 或文本含 ▶
    const pi = cells.findIndex((x) => x.title.includes('▶') || x.text.includes('▶'));
    if (pi < 0) continue;
    const platCell = cells[pi];
    const aid = ((platCell.title.match(/▶\s*(\d+)/) || [])[1]) || '';
    const area = AREA_BY_AID[aid] || platCell.text.replace(/^.*▶/, '').trim();
    if (!area) continue;
    // 时间
    const timeCell = cells.find((x) => x.cls.includes('delivery-time-cell')) || cells[pi - 1];
    const time = ((timeCell && timeCell.text.match(/[\d-]+ [\d:]+/)) || [''])[0];
    // 数量 / 单价：优先 data-type（新单），老单回退到平台格后的固定偏移
    const pick = (idx, type) => {
      const byType = cells.find((x) => x.type === type);
      if (byType) return byType.value || byType.text;
      const cc = cells[idx];
      return cc ? (cc.value || cc.text) : '';
    };
    const qty = parseInt(pick(pi + 1, 'qty'), 10) || 0;
    const price = parseFloat(pick(pi + 3, 'delivery_price'));
    if (!(price > 0)) continue;
    rows.push({ id, aid, area, time, price, qty });
  }
  return rows;
}

// 抓一页发货列表（可指定平台 aid 与时间窗）
async function fetchDeliveryRows(aid, hoursBack) {
  const now = new Date();
  const start = new Date(now.getTime() - hoursBack * 60 * 60 * 1000);
  const fmt = (d) => {
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}+${p(d.getHours())}%3A${p(d.getMinutes())}`;
  };
  const url = `${BASE}/order/admin_delivery/index.html?genre=0&gid=${GID}&aid=${aid || 0}&cid=${CID}`
    + `&status=-1&op_id=0&is_stock=&show_ccy=-1&start=${fmt(start)}&end=${fmt(now)}&keyword=&sn=&wid=`;
  const res = await request('GET', url);
  return parseDeliveryPrice(res.text);
}

async function readLatestPrice() {
  await ensureLogin();

  // 1) 近 48 小时全平台
  const rows = await fetchDeliveryRows(0, 48);
  const normal = rows.filter((r) => !(r.qty === 1 && r.price >= 10)); // 排除数量1且单价异常高的整单
  const byArea = {};
  for (const r of normal) {
    if (!byArea[r.area] || r.time > byArea[r.area].time) {
      byArea[r.area] = { area: r.area, price: r.price, time: r.time, id: r.id };
    }
  }

  // 2) 缺哪个平台就单独按 aid 往前找 7 天（保证三端都有行，避免 PC 这类当天无新单的直接消失）
  const WANT = ['PS', 'Xbox', 'PC'];
  const AID_OF = { PS: 21764, Xbox: 21766, PC: 21768 };
  const STALE_MS = 48 * 60 * 60 * 1000;
  const nowMs = Date.now();
  for (const area of WANT) {
    if (byArea[area]) continue;
    try {
      const extra = (await fetchDeliveryRows(AID_OF[area], 24 * 7))
        .filter((r) => r.area === area && !(r.qty === 1 && r.price >= 10));
      if (!extra.length) continue;
      const latest = extra.reduce((a, b) => (b.time > a.time ? b : a));
      byArea[area] = { area, price: latest.price, time: latest.time, id: latest.id, stale: true };
    } catch (e) {
      console.error(`[${area}] 补抓历史单价失败:`, e.message);
    }
  }

  // 3) 固定顺序 PS / Xbox / PC，标记超出 48h 的旧单
  const result = WANT.filter((a) => byArea[a]).map((a) => {
    const it = byArea[a];
    if (!it.stale) {
      const t = it.time.replace(/^(\d+)-(\d+)-(\d+) (\d+):(\d+):(\d+)$/, '20$1-$2-$3T$4:$5:$6');
      it.stale = !(new Date(t).getTime() >= nowMs - STALE_MS);
    }
    return it;
  });

  return { rate: RATE, fetchedAt: new Date().toISOString(), platforms: result, rawCount: rows.length };
}

// ===== 读取我方 mmoexp 前台三端售价 =====
// 前台按 aid 区分平台，POST /ajax/goods 返回该平台全部档位（免登录）
const MMOEXP = {
  url: 'https://www.mmoexp.com/ajax/goods',
  referer: 'https://www.mmoexp.com/Nba-2k27/Vc.html',
  gid: 1329,
  cid: 9633,
  siteId: 266,
  topCid: 1,
  areas: [
    { area: 'PS', aid: 21595, title: 'PlayStation 5' },
    { area: 'Xbox', aid: 21591, title: 'Xbox Series X|S' },
    { area: 'PC', aid: 21597, title: 'PC Platform' },
  ],
};

function fetchMmoexpPrice(aid) {
  return new Promise((resolve, reject) => {
    const body = `Game_id=${MMOEXP.gid}&top_cid=${MMOEXP.topCid}&aid=${aid}&cid=${MMOEXP.cid}&site_id=${MMOEXP.siteId}`;
    const req = https.request(MMOEXP.url, {
      method: 'POST',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154.0 Safari/537.36',
        'Referer': MMOEXP.referer,
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Content-Length': Buffer.byteLength(body),
      },
    }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        try {
          const j = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          const item = j && j.goods && j.goods.index && j.goods.index.list && j.goods.index.list[0];
          if (!item) throw new Error('返回结构异常');
          resolve({
            title: item.game_area_format,
            price: parseFloat(item.unit_price),
            tiers: Object.keys(item.goods_list || {}).length,
          });
        } catch (e) {
          reject(new Error('解析失败: ' + e.message));
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(20000, () => req.destroy(new Error('请求超时')));
    req.write(body);
    req.end();
  });
}

async function readMmoexpPrices() {
  const out = [];
  for (const a of MMOEXP.areas) {
    try {
      const r = await fetchMmoexpPrice(a.aid);
      out.push({ area: a.area, title: r.title, price: r.price, tiers: r.tiers });
    } catch (e) {
      out.push({ area: a.area, title: a.title, price: null, error: e.message });
    }
  }
  return out;
}

// ===== 竞品价格实时抓取（u4gm / iggm / u7buy） =====
// 三家用 Node 直连会被 Cloudflare 403，统一走系统 curl（与 fetch_vc_prices.py 同一套口径）
const CURL = process.platform === 'win32' ? 'curl.exe' : 'curl';
const CMP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const U4GM_CODES = { PS: 'ps', Xbox: 'xbox', PC: 'pc' };
const IGGM_SERVERS = { PS: '27443', Xbox: '27441', PC: '27439' };
const U7_SPU = '2095709820309200897';
const U7_CLIENT = '94f670c954182e9c30535fa9cad35983';
const U7_BASE = 'https://www.u7buy.com/prod-api';

function curlGet(url, headers = {}, timeout = 30, cookieJar = null) {
  return new Promise((resolve, reject) => {
    const args = ['-s', '--max-time', String(timeout), '-A', CMP_UA, '-L'];
    // cookieJar：IGGM 对没有会话 Cookie 的 goods_ajax 会返回反爬加载页（HTTP 403），
    // 必须先访问一次商品页把会话写进 jar，再带 -b/-c 复用（2026-09-30 线上实测）
    if (cookieJar) args.push('-b', cookieJar, '-c', cookieJar);
    for (const [k, v] of Object.entries(headers)) args.push('-H', `${k}: ${v}`);
    args.push(url);
    execFile(CURL, args, { maxBuffer: 32 * 1024 * 1024, timeout: (timeout + 10) * 1000 }, (err, stdout, stderr) => {
      if (err) return reject(new Error('curl 失败: ' + (stderr || err.message)));
      resolve(stdout);
    });
  });
}

// U4GM：产品页 server_code 切平台，单价在 data-unit-price
async function fetchU4gm() {
  const price = {};
  for (const [plat, code] of Object.entries(U4GM_CODES)) {
    const html = await curlGet(`https://www.u4gm.com/nba-2k27/vc?server_code=${code}`,
      { 'X-Requested-With': 'XMLHttpRequest', Referer: 'https://www.u4gm.com/nba-2k27/vc' });
    const m = html.match(/data-unit-price="([\d.]+)"/);
    price[plat] = m ? parseFloat(m[1]) : null;
  }
  return { price };
}

// IGGM：官方 goods_ajax，server_id 区分平台；现返回 JSON，取 data.one_goods.price
// 2026-09-30 线上修复：无会话 Cookie 时该接口返回反爬加载页（HTTP 403），
// 需先 GET 商品页建立会话，再带 sort/goods_name/tag/page 参数请求（缺参数同样会被拦）。
const IGGM_REFERER = 'https://www.iggm.com/nba-2k/2k27-vc';
const IGGM_COOKIE_JAR = path.join(__dirname, '.iggm.cookies.txt');
async function fetchIggm() {
  const price = {};
  try {
    await curlGet(IGGM_REFERER, {}, 25, IGGM_COOKIE_JAR);
  } catch (e) { /* 预热失败仍继续，后续会回退到 HTML 匹配 */ }
  for (const [plat, sid] of Object.entries(IGGM_SERVERS)) {
    const txt = await curlGet(
      `https://www.iggm.com/goods/goods_ajax?template_type=golds&server_id=${sid}&cate_id=0&sort=0&goods_name=&tag=&page=1`,
      { 'X-Requested-With': 'XMLHttpRequest', Referer: IGGM_REFERER }, 30, IGGM_COOKIE_JAR);
    let v = null;
    try {
      const g = JSON.parse(txt).data.one_goods;
      if (g && g.price) v = parseFloat(g.price);
    } catch (e) { /* 结构变化时回退到 HTML 匹配 */ }
    if (v === null) {
      const m = txt.match(/data-unit-price="([\d.]+)"/);
      v = m ? parseFloat(m[1]) : null;
    }
    price[plat] = v;
  }
  return { price };
}

// '100K' / '1M' -> 100000 / 1000000
function u7ToVc(face) {
  const m = String(face == null ? '' : face).trim().toUpperCase().replace(/,/g, '').match(/^([\d.]+)\s*([KMB]?)$/);
  if (!m) return null;
  return parseFloat(m[1]) * ({ '': 1, K: 1e3, M: 1e6, B: 1e9 }[m[2]]);
}

const U7_PLAT = { PS5: 'PS', PS4: 'PS', PlayStation: 'PS', XBOX: 'Xbox', Xbox: 'Xbox', PC: 'PC' };

// U7BUY：getFaceValueList 四参数缺一不可（areaId 才是平台开关），免登录
async function fetchU7buy() {
  const hdr = {
    clientid: U7_CLIENT, 'Content-Language': 'en', 'content-currency': 'USD',
    Accept: 'application/json', Referer: 'https://www.u7buy.com/nba-2k27/vc',
  };
  const fc = JSON.parse(await curlGet(
    `${U7_BASE}/product/urlMapping/topUpProductInfo/getFilterConditions?spuId=${U7_SPU}`, hdr));
  const cat = (fc.data || [])[0];
  if (!cat) throw new Error('getFilterConditions 返回空');
  const dv = (cat.deliveryInfoVoList || [])[0] || {};

  const price = {}, entryFace = {}, best = {}, bestFace = {};
  for (const r of (dv.regionInfoList || [])) {
    const plat = U7_PLAT[r.areaName] || r.areaName;
    const js = JSON.parse(await curlGet(
      `${U7_BASE}/product/urlMapping/topUpProductInfo/getFaceValueList?spuId=${U7_SPU}`
      + `&categoryId=${cat.categoryId}&deliveryId=${dv.deliveryId}&areaId=${r.areaId}`, hdr));
    const tiers = (js.data || [])
      .map((it) => {
        const vc = u7ToVc(it.faceValue);
        const p = parseFloat(it.price || 0);
        return { face: it.faceValue, vc, per1k: vc ? p / (vc / 1000) : null, sold: !!it.soldOutFlag };
      })
      .filter((t) => !t.sold && t.per1k)
      .sort((a, b) => a.vc - b.vc);
    if (!tiers.length) { price[plat] = null; continue; }
    price[plat] = +tiers[0].per1k.toFixed(4);      // 最小档单价（表格口径）
    entryFace[plat] = tiers[0].face;
    const b = tiers.reduce((m, t) => (t.per1k < m.per1k ? t : m), tiers[0]);
    best[plat] = +b.per1k.toFixed(4);              // 大额档最低单价
    bestFace[plat] = b.face;
  }
  return { price, entryFace, best, bestFace };
}

async function readCompetitors() {
  const jobs = [['u4gm', fetchU4gm], ['iggm', fetchIggm], ['u7buy', fetchU7buy]];
  const sites = {};
  await Promise.all(jobs.map(async ([key, fn]) => {
    try {
      sites[key] = Object.assign({ ok: true }, await fn());
    } catch (e) {
      sites[key] = { ok: false, error: e.message };
    }
  }));
  return { fetchedAt: new Date().toISOString(), sites };
}

// ===== 改价写入 =====
// 真实写入通道：p2pah 新后台 admin-api.p2pah.cn 的 POST /admin/goods.Goods/edit
// 目标：NBA 2K27（gid=1329）/ 产品模型 VC（mid=42278471）/ 站点 ALL（site_id=0）三端产品，
//       写入字段 unit_price（「每个价格」，前台售价 = unit_price × 数量 × 折扣 ÷ 100）
//   PlayStation 5   id=165466527  aid=21595
//   Xbox Series X|S id=165466561  aid=21591
//   PC Platform     id=165466595  aid=21597
// 流程：读回现值 → 提交 → 再复核；全过程记 apply_log.jsonl
const WRITE_READY = String(process.env.WRITE_READY || 'true').toLowerCase() !== 'false';
const APPLY_LOG = path.join(__dirname, 'apply_log.jsonl');
const P2PAH_SCRIPT = path.join(__dirname, 'p2pah_api.py');
const ADMIN_PRICE_JSON = path.join(__dirname, '.admin_prices.tmp.json');

const AREA_TO_PRODUCT = {
  PS:   { platform: 'PlayStation 5',   id: 165466527, aid: 21595 },
  Xbox: { platform: 'Xbox Series X|S', id: 165466561, aid: 21591 },
  PC:   { platform: 'PC Platform',     id: 165466595, aid: 21597 },
};

// 调 Python 写入（复用已验证的 curl + batoken 通道）
function adminWrite(priceMap) {
  return new Promise((resolve, reject) => {
    fs.writeFileSync(ADMIN_PRICE_JSON, JSON.stringify({ prices: priceMap }), 'utf8');
    execFile(PYTHON, [P2PAH_SCRIPT, 'write', ADMIN_PRICE_JSON],
      { timeout: 180000, maxBuffer: 16 * 1024 * 1024 },
      (err, stdout, stderr) => {
        const line = String(stdout).trim().split('\n').filter(Boolean).pop();
        let js = null;
        try { js = JSON.parse(line); } catch (e) { /* 下面统一报错 */ }
        if (!js) {
          return reject(new Error('写入返回不可解析：' + ((stderr || '').trim() || String(stdout).slice(0, 300) || (err && err.message))));
        }
        resolve(js);
      });
  });
}

function appendApplyLog(entry) {
  try {
    fs.appendFileSync(APPLY_LOG, JSON.stringify(entry) + '\n', 'utf8');
  } catch (e) {
    console.error('[审计日志写入失败]', e.message);
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (c) => { raw += c; if (raw.length > 1e6) req.destroy(); });
    req.on('end', () => {
      try { resolve(raw ? JSON.parse(raw) : {}); } catch (e) { reject(e); }
    });
    req.on('error', reject);
  });
}

async function applyPrices(payload, operator) {
  const platforms = Array.isArray(payload.platforms) ? payload.platforms : [];
  if (!platforms.length) throw new Error('缺少 platforms 数据');
  const bad = platforms.filter((p) => !(Number(p.price) > 0));
  if (bad.length) throw new Error('存在非法售价：' + bad.map((b) => b.area).join('/'));

  const priceMap = {};
  for (const p of platforms) {
    const t = AREA_TO_PRODUCT[p.area];
    if (!t) throw new Error('未知平台：' + p.area);
    priceMap[t.platform] = Number(p.price);
  }

  let write = { ok: false, error: 'WRITE_READY=false，未执行' };
  if (WRITE_READY) {
    write = await adminWrite(priceMap);
  }

  const entry = {
    at: new Date().toISOString(),
    rate: payload.rate,
    marginMin: payload.marginMin,
    marginMax: payload.marginMax,
    mode: payload.mode,
    operator: operator || 'unknown',
    platforms: platforms.map((p) => ({ area: p.area, cost: p.cost, price: p.price, margin: p.margin })),
    written: WRITE_READY && write.ok === true,
    result: write,
  };
  appendApplyLog(entry);

  if (!write.ok) {
    return { ok: false, error: write.error || '写入未成功', detail: write, entry };
  }
  return { ok: true, entry, write };
}

// ===== HTTP 服务 =====
const server = http.createServer(async (req, res) => {
  // CORS（白名单未配置时保持 *，但业务接口另有令牌鉴权兜底）
  res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN || '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Access-Token');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);
  const sendJson = (code, data) => {
    res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(data));
  };

  try {
    if (url.pathname === '/api/health') {
      return sendJson(200, { ok: true });
    }
    // 鉴权：启用口令时，其余业务接口必须携带有效 token（operator 同时用于审计留痕）
    let operator = null;
    if (AUTH_ENABLED) {
      operator = resolveOperator(req);
      if (!operator) {
        return sendJson(401, { ok: false, error: '未授权：请提供有效令牌（X-Access-Token 或 Authorization: Bearer）' });
      }
    }
    if (url.pathname === '/api/read') {
      const data = await readLatestPrice();
      return sendJson(200, { ok: true, ...data });
    }
    // 我方 mmoexp 前台三端实时售价（无需登录）
    if (url.pathname === '/api/current') {
      const platforms = await readMmoexpPrices();
      return sendJson(200, {
        ok: true,
        source: 'mmoexp.com',
        fetchedAt: new Date().toISOString(),
        platforms,
      });
    }
    // 三家竞品实时价格（u4gm / iggm / u7buy，无需登录）
    if (url.pathname === '/api/competitors') {
      const data = await readCompetitors();
      return sendJson(200, { ok: true, ...data });
    }
    // 改价写入（真实写入 admin-api.p2pah.cn 三端 VC 售价；全过程审计留痕）
    if (url.pathname === '/api/apply') {
      const payload = await readBody(req);
      const r = await applyPrices(payload, operator);
      if (!r.ok) {
        return sendJson(502, {
          ok: false,
          error: r.error,
          detail: r.detail,
        });
      }
      return sendJson(200, { ok: true, results: r.write.results, verify: r.write.verify });
    }
    sendJson(404, { ok: false, error: 'not found' });
  } catch (e) {
    console.error('[错误]', e.message);
    sendJson(500, { ok: false, error: e.message });
  }
});

server.listen(PORT, BIND_HOST, () => {
  loadCookie();
  console.log(`改价后端服务已启动: http://${BIND_HOST}:${PORT}`);
  console.log(`  - GET /api/read         读取最新采购单价（后端自动登录）`);
  console.log(`  - GET /api/current      我方 mmoexp 前台三端售价`);
  console.log(`  - GET /api/competitors  三家竞品实时价格（u4gm/iggm/u7buy）`);
  console.log(`  - GET /api/health       健康检查`);
});
