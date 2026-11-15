// Runs Smart Score's own slash command in the logged-in Discord desktop UI.
// The public reply remains Smart Score's; FC Assistant consumes it as usual.
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, appendFileSync, renameSync, mkdirSync, openSync, closeSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const CDP_DIR = process.env.FC27_DISCORD_CDP_DIR || 'D:/Deepseek Harness/discord-cdp';
const KEY = process.env.FC27_SSH_KEY ||
  'D:/Deepseek Harness/fs-migration-20261104/migration-20261104/secrets/current/fs_admin';
const SCOUT = '/opt/mmoexp-fc-community/var/matchday-scout-latest.json';
const ROUTES = {
  test: 'https://discord.com/channels/1565922092518613064/1568260661010497627',
  official: 'https://discord.com/channels/1041923524601851914/1571043454136484082',
};
const STATE_DIR = process.env.FC27_SMARTSCORE_STATE_DIR || join(CDP_DIR, 'state');
const clean = value => String(value || '').replace(/[\u200b-\u200d\u2060\ufeff]/g, '').trim();

export function parseArgs(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key === '--send' || key === '--navigate') {
      if (flags[key]) throw Error('Duplicate flag ' + key);
      flags[key] = true;
    } else if (['--target', '--team', '--scout-file'].includes(key) && argv[i + 1]) {
      if (flags[key]) throw Error('Duplicate option ' + key);
      flags[key] = argv[++i];
    } else {
      throw Error('Invalid argument ' + key);
    }
  }
  const target = flags['--target'] || 'test';
  if (!ROUTES[target]) throw Error('Target must be test or official');
  if (flags['--team'] && flags['--scout-file']) throw Error('Choose a team or a scout file');
  return { target, team: flags['--team'], scoutFile: flags['--scout-file'],
    send: !!flags['--send'], navigate: !!flags['--navigate'] };
}

function checkedTeam(value) {
  if (typeof value !== 'string' || !/^[\p{L}\p{N} .’'&–-]{2,60}$/u.test(value.trim()))
    throw Error('Invalid team name');
  return value.trim();
}

export function planFromScout(data, now = Date.now()) {
  if (!data || !Array.isArray(data.matches) || data.matches.length > 2)
    throw Error('Invalid Hermes shortlist');
  const generated = Date.parse(data.generated_at_utc);
  if (!Number.isFinite(generated) || generated > now + 120000 || now - generated > 3 * 3600000)
    throw Error('Hermes shortlist is stale');
  const teams = [...new Set(data.matches.map(item => checkedTeam(item.home)))];
  const fixtureKeys = Object.fromEntries(data.matches.map(item => {
    const home = checkedTeam(item.home);
    const away = checkedTeam(item.away);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(item.date)) throw Error('Invalid fixture date');
    return [home, item.date + ':' + home + ':' + away];
  }));
  return { id: data.generated_at_utc, teams, fixtureKeys };
}

function readScout(file) {
  if (file) return JSON.parse(readFileSync(file, 'utf8'));
  const out = execFileSync('ssh', [
    '-i', KEY, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
    '-o', 'ConnectTimeout=10', 'root@47.85.224.112', 'cat ' + SCOUT,
  ], { encoding: 'utf8', timeout: 20000, maxBuffer: 65536 });
  return JSON.parse(out);
}

function save(path, value) {
  const temporary = path + '.' + process.pid + '.tmp';
  writeFileSync(temporary, JSON.stringify(value, null, 2));
  renameSync(temporary, path);
}

async function receipt(api, route, before, team) {
  return api.waitFor(async () => {
    if (await api.where() !== route) throw Error('Discord moved away during command');
    const rows = await api.evaluate(`(() => [...document.querySelectorAll('[id^="chat-messages-"]')]
      .map(e => ({id:e.id.split('-').pop(),text:e.innerText,
        avatars:[...e.querySelectorAll('img[src*="/avatars/"]')].map(i=>i.getAttribute('src')||'')}))
      .filter(x => /smart-score/i.test(x.text) && /Upcoming Matches/i.test(x.text) &&
        x.avatars.some(a=>a.includes('/avatars/1237241595674361962/')) &&
        x.avatars.some(a=>a.includes('/avatars/1496068397757366273/'))))()`);
    const matches = rows.filter(x => /^\d{16,20}$/.test(x.id) &&
      BigInt(x.id) > before && (clean(x.text).toLowerCase().includes(team.toLowerCase()) ||
        /No upcoming matches in the selected time range/i.test(x.text)));
    if (matches.length > 1) throw Error('Multiple Smart Score replies; inspect channel');
    const found = matches[0];
    return found ? { message_id: found.id, url: route + '/' + found.id,
      matched: clean(found.text).toLowerCase().includes(team.toLowerCase()) } : null;
  }, 12000);
}

async function issue(api, route, team, beforeSubmit) {
  if (await api.where() !== route) throw Error('Wrong target channel');
  if (!await api.ensureComposer(route)) throw Error('Target composer unavailable');
  if (clean(await api.text()) === '/live upcoming') {
    try { await api.replaceDraft({ url: route }, ''); }
    catch (error) {
      if (!await api.waitFor(async () => clean(await api.text()) === '', 1500))
        throw error;
    }
  }
  if (clean(await api.text())) throw Error('Target draft is not empty');
  const ids = await api.evaluate(`[...document.querySelectorAll('[id^="chat-messages-"]')]
    .map(e => e.id.split('-').pop()).filter(x => /^\d{16,20}$/.test(x))`);
  // The message list can briefly unmount while Discord opens the slash menu.
  // Use wall time too, so an old card can never count as this command's reply.
  const cutoff = (BigInt(Date.now() - 5000 - 1420070400000) << 22n);
  const before = ids.reduce((max, id) => BigInt(id) > max ? BigInt(id) : max, cutoff);
  if (!await api.focusEditor()) throw Error('Cannot focus target composer');
  await api.type('/live');
  const command = await api.waitFor(async () => {
    if (await api.where() !== route) throw Error('Discord moved away');
    const rows = (await api.options()).filter(x =>
      x.text.includes('/live upcoming') && /smart-score/i.test(x.text));
    return rows.length === 1 ? rows[0] : null;
  });
  if (!command || !await api.clickOption(command.i, command.text))
    throw Error('Smart Score command not found');
  if (await api.where() !== route || !/\/live upcoming/.test(await api.text() || ''))
    throw Error('Wrong command selected');
  const windowOption = await api.waitFor(async () => {
    const rows = (await api.options()).filter(x => x.text.startsWith('within_hours '));
    return rows.length === 1 ? rows[0] : null;
  });
  if (!windowOption || !await api.clickOption(windowOption.i, windowOption.text))
    throw Error('Smart Score time-window option not found');
  if (await api.where() !== route) throw Error('Discord moved away');
  await api.type('48');
  if (!clean(await api.text()).includes('48')) throw Error('Time-window input not visible');
  await api.evaluate(`(() => {const e=document.querySelector('[role="textbox"][contenteditable="true"]');
    if(!e)return false;e.dispatchEvent(new KeyboardEvent('keydown',
    {key:'Tab',code:'Tab',keyCode:9,which:9,bubbles:true,cancelable:true}));return true;})()`);
  const option = await api.waitFor(async () => {
    const rows = (await api.options()).filter(x => x.text.startsWith('team '));
    return rows.length === 1 ? rows[0] : null;
  });
  if (!option || !await api.clickOption(option.i, option.text))
    throw Error('Smart Score team option not found');
  if (await api.where() !== route) throw Error('Discord moved away');
  await api.type(team);
  if (!clean(await api.text()).includes(team)) throw Error('Team input not visible');
  beforeSubmit();
  await api.enter();
  const found = await receipt(api, route, before, team);
  if (!found) throw Error('Command outcome unknown; inspect channel before retry');
  return found;
}

export async function run(argv = process.argv.slice(2)) {
  const opts = parseArgs(argv);
  const plan = opts.team ?
    { id: 'manual-' + new Date().toISOString().slice(0, 10), teams: [checkedTeam(opts.team)] } :
    planFromScout(readScout(opts.scoutFile));
  if (!opts.send) return { dry_run: true, target: opts.target, ...plan };
  if (!plan.teams.length) return { target: opts.target, results: [], reason: 'No Hermes picks' };
  mkdirSync(STATE_DIR, { recursive: true });
  const lock = join(STATE_DIR, 'smartscore-upcoming.lock');
  const statePath = join(STATE_DIR, 'smartscore-upcoming-' + opts.target + '.json');
  const fd = openSync(lock, 'wx');
  let client, api, initial, route;
  try {
    const state = (() => { try { return JSON.parse(readFileSync(statePath, 'utf8')); }
                        catch (error) { if (error.code === 'ENOENT') return {}; throw error; } })();
    const cdp = await import(pathToFileURL(join(CDP_DIR, 'cdp.mjs')).href);
    const { makeApi } = await import(pathToFileURL(join(CDP_DIR, 'push.mjs')).href);
    const page = await cdp.pageTarget();
    client = await cdp.connect(page.webSocketDebuggerUrl);
    api = makeApi(client);
    api.evaluate = expression => cdp.evaluate(client, expression);
    route = ROUTES[opts.target];
    initial = await api.where();
    if (initial !== route) {
      if (!opts.navigate) throw Error('Discord is not on target channel');
      if (clean(await api.text())) throw Error('Current channel has a draft');
      await api.navigate(route);
      if (!await api.waitFor(async () => (await api.where()) === route))
        throw Error('Target navigation failed');
    }
    const results = [];
    for (const team of plan.teams) {
      const key = plan.fixtureKeys?.[team] || plan.id + ':' + team;
      if (state[key]) {
        results.push({ team, skipped: state[key].status });
        continue;
      }
      let attempted = false;
      try {
        const sent = await issue(api, route, team, () => {
          attempted = true;
          state[key] = { status: 'sending', at: new Date().toISOString() };
          save(statePath, state);
        });
        state[key] = { status: 'sent', ...sent };
        save(statePath, state);
        results.push({ team, ...sent });
      } catch (error) {
        try {
          if (await api.where() === route && clean(await api.text()).startsWith('/live'))
            await api.replaceDraft({ url: route }, '');
        } catch {}
        if (attempted) {
          state[key] = { status: 'unknown', at: new Date().toISOString() };
          save(statePath, state);
        }
        throw error;
      }
    }
    return { target: opts.target, results };
  } finally {
    if (api && initial && route && initial !== route &&
        initial.startsWith('https://discord.com/channels/')) {
      try {
        if (await api.where() === route)
          await api.evaluate(`location.href=${JSON.stringify(initial)}`);
      } catch {}
    }
    client?.close();
    closeSync(fd);
    unlinkSync(lock);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const log = (status, detail) => {
    mkdirSync(STATE_DIR, { recursive: true });
    appendFileSync(join(STATE_DIR, 'smartscore-upcoming-run.jsonl'),
      JSON.stringify({ at: new Date().toISOString(), status, detail }) + '\n');
  };
  run().then(result => { console.log(JSON.stringify(result)); log('ok', result); })
    .catch(error => {
      console.error('ERROR: ' + error.message);
      log('error', error.message);
      process.exitCode = 1;
    });
}
