const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(process.argv[2] ||
  path.join(__dirname, '../opt/fs-access-policy/web/app.js'), 'utf8');
const section = (from, to) => {
  const start = source.indexOf(from);
  const end = source.indexOf(to, start);
  assert(start >= 0 && end > start, 'existing form functions must be present');
  return source.slice(start, end);
};
const apiCode = section('  function api(', '  /* ------------------------------------------------------------ 载入 */');
const formCode = section('  function setPassword(', '  function closeDrawer(');

async function submit(member, value = 'fixture-value-12', status = 200) {
  const requests = [];
  const messages = [];
  const input = { value, focus() { this.focused = true; } };
  const button = {};
  const context = {
    API: './api/', csrf: () => 'fixture-csrf',
    toast: (...args) => messages.push(args),
    fetch: async (url, config) => {
      requests.push({ url, ...config, body: JSON.parse(config.body) });
      return { ok: status === 200, status,
        json: async () => status === 200 ? { ok: true } : { error: 'fixture-denied' } };
    },
    member, input, button,
  };
  vm.runInNewContext(apiCode + formCode + '\nsetPassword(member, input, button);', context);
  await new Promise(resolve => setImmediate(resolve));
  return { requests, input, button, messages };
}

(async () => {
  const uuid = '11111111-2222-4333-8444-555555555555';
  const cases = [
    [{ kind: 'native', name: 'dot_fc_observer', subject: 'dot_fc_observer' }, 'native:dot_fc_observer'],
    [{ kind: 'native', name: 'wulv', subject: 'wulv' }, 'native:wulv'],
    [{ kind: 'native', name: 'a.b-c_d', subject: 'a.b-c_d' }, 'native:a.b-c_d'],
    [{ kind: 'registered', name: 'dot_fc_observer', subject: 'reg:' + uuid }, 'reg:' + uuid],
    [{ name: 'dot_fc_observer', subject: 'dot_fc_observer' }, 'dot_fc_observer'],
    [{ kind: 'unknown', name: 'wulv', subject: 'wulv' }, 'wulv'],
  ];
  for (const [member, expected] of cases) {
    const before = JSON.stringify(member);
    const result = await submit(member);
    assert.equal(result.requests.length, 1);
    const request = result.requests[0];
    assert.equal(request.url, './api/member/password');
    assert.equal(request.method, 'POST');
    assert.equal(request.credentials, 'same-origin');
    assert.equal(request.headers['X-CSRF-Token'], 'fixture-csrf');
    assert.equal(request.headers['Content-Type'], 'application/json');
    assert.equal(request.body.subject, expected);
    assert.equal(JSON.stringify(member), before, 'role-binding identity must remain unchanged');
    assert.equal(result.input.value, '');
    assert.equal(result.button.disabled, false);
  }
  for (const length of [0, 11, 129]) {
    assert.equal((await submit(cases[0][0], 'x'.repeat(length))).requests.length, 0);
  }
  for (const length of [12, 128]) {
    assert.equal((await submit(cases[0][0], 'x'.repeat(length))).requests.length, 1);
  }
  const rejected = await submit(cases[0][0], 'fixture-value-12', 403);
  assert.equal(rejected.button.disabled, false);
  assert.equal(rejected.input.value, 'fixture-value-12');
  assert.equal(rejected.messages[0][0], 'fixture-denied');
  console.log(JSON.stringify({ cases: 12, passed: true, network_requests: 0, credential_writes: 0 }));
})().catch(error => { console.error(error); process.exitCode = 1; });
