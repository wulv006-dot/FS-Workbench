// 发布前预检：用模块自己的 projectRelease 校验 current.json，先失败再上线。
// 用法：node tools/campaign_config_preflight.mjs /path/to/current.json
// 退出码 0=通过；1=校验失败（打印具体错误码）；2=用法错误。
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const modulePath = process.env.CAMPAIGN_SNAPSHOT_MODULE || new URL('../releases/fs-dashboard/campaign-analytics-20261023/app/runtime/snapshot.mjs', import.meta.url).href;
const {projectRelease, validateSnapshot} = await import(modulePath);
const validate = validateSnapshot || projectRelease;

const target = process.argv[2];
if (!target) {
  console.error('usage: node tools/campaign_config_preflight.mjs <current.json>');
  process.exit(2);
}
const input = JSON.parse(fs.readFileSync(path.resolve(target), 'utf8'));
try {
  const release = validate(input);
  const bindings = release.native_checkout?.bindings || [];
  const covered = new Set(bindings.map(b => b.page_id + '|' + b.product_key));
  const missing = [];
  for (const page of release.pages) {
    if (page.page_id === 'seasonal-vault') continue;
    for (const key of page.product_keys) {
      if (!covered.has(page.page_id + '|' + key)) missing.push(page.page_id + '|' + key);
    }
  }
  console.log(JSON.stringify({
    ok: missing.length === 0,
    release_id: release.release_id,
    config_hash: release.config_hash,
    pages: release.pages.map(p => ({page_id: p.page_id, keys: p.product_keys.length})),
    bindings: bindings.length,
    missing_bindings: missing.slice(0, 20),
  }, null, 2));
  process.exit(missing.length ? 1 : 0);
} catch (error) {
  console.error(JSON.stringify({ok: false, code: error.code || error.message, hint: 'native_checkout 或页面商品结构与 product_keys 不一致'}, null, 2));
  process.exit(1);
}
