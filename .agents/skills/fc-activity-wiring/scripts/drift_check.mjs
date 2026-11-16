// 发布前"漂移核对"：线上要被替换的文件，是否和上一版仓库内容一致（去掉 \r 后比较）。
//
// 用法：
//   1. 本机生成上一版的哈希清单（<prev> 是上一次发布对应的提交，通常是本次 PR 合并前的 main）：
//        node drift_check.mjs list <prev提交> <模块相对路径...> > old_hashes.txt
//   2. 把 old_hashes.txt 传到 187，在 187 上比较：
//        node drift_check.mjs compare old_hashes.txt        # 需要 187 上有 node；没有就用下面的 shell 版
//      187 上没有 node 时用 shell：
//        while read f want; do p=/opt/fs-campaign-dashboard/${f#app/}; \
//          have=$(tr -d '\r' < $p | sha256sum | cut -c1-16); \
//          [ "$have" = "$want" ] && echo "same   $f" || echo "DRIFT  $f"; done < old_hashes.txt
//   任何 DRIFT 都先停下问清来源，不要覆盖。
import fs from 'node:fs';
import cp from 'node:child_process';
import crypto from 'node:crypto';
const [mode, a, ...rest] = process.argv.slice(2);
const MODULE = 'releases/fs-dashboard/campaign-analytics-20261023';
if (mode === 'list') {
  const repo = process.env.FS_REPO || cp.execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
  for (const f of rest) {
    const body = cp.execFileSync('git', ['-C', repo, 'show', `${a}:${MODULE}/${f}`], { maxBuffer: 64 * 1024 * 1024 });
    console.log(f, crypto.createHash('sha256').update(Buffer.from(body.toString('utf8').replace(/\r/g, ''))).digest('hex').slice(0, 16));
  }
} else if (mode === 'compare') {
  for (const line of fs.readFileSync(a, 'utf8').split('\n').filter(Boolean)) {
    const [f, want] = line.split(' ');
    const p = '/opt/fs-campaign-dashboard/' + f.replace(/^app\//, '');
    const have = fs.existsSync(p) ? crypto.createHash('sha256').update(Buffer.from(fs.readFileSync(p, 'utf8').replace(/\r/g, ''))).digest('hex').slice(0, 16) : 'missing';
    console.log(have === want ? 'same  ' : 'DRIFT ', f);
  }
} else {
  console.error('usage: drift_check.mjs list <prev-commit> <files...> | compare <hash-file>');
  process.exit(2);
}
