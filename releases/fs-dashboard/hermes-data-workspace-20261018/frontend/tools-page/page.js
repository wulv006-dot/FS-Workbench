import {protectedRead, sessionIdentity} from '/dashboard/workspace-assets/workspace-native-20261006-ba0a83afd594/runtime.js';

const status = document.getElementById('page-status');
const host = document.getElementById('workspace-host');
const theme = document.getElementById('theme');
const controller = new AbortController();
let identity = null;
let widget = null;

function show(message, error = false) {
  status.textContent = message;
  status.dataset.state = error ? 'error' : 'available';
}

function deny(code) {
  controller.abort();
  widget?.dispose();
  widget = null;
  identity = null;
  host.hidden = true;
  show(code === 403 ? '当前账号未获此工具页授权。' : '登录已失效，请重新登录。', true);
}

function scopedSignal(signal) {
  return signal ? AbortSignal.any([controller.signal, signal]) : controller.signal;
}

function stylesheet(root, path) {
  return new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = path;
    link.onload = resolve;
    link.onerror = () => reject(Error('style_unavailable'));
    root.append(link);
  });
}

async function start() {
  try {
    identity = await sessionIdentity(controller.signal);
    if (controller.signal.aborted) return;
    const moduleURL = new URL(document.body.dataset.moduleUrl || '', location.href);
    if (moduleURL.origin !== location.origin || !/^\/dashboard\/workspace-assets\/workspace-native-20261006-[a-f0-9]{12}\/data-workspace\.js$/.test(moduleURL.pathname)) throw Error('invalid_data_module');
    const {mountDataWorkspace, hermesHandoffURL} = await import(moduleURL.href);
    if (controller.signal.aborted) return;
    const root = host.attachShadow({mode: 'open'});
    await Promise.all([
      stylesheet(root, '/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/fs-ui.css'),
      stylesheet(root, '/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/ui/native-alias.css'),
      stylesheet(root, '/dashboard/workspace-assets/workspace-native-20261006-561eda9b98e2/business.css')
    ]);
    if (controller.signal.aborted) return;
    const yesterday = new Date(Date.now() + 8 * 3600000 - 86400000).toISOString().slice(0, 10);
    const read = (url, options = {}) => protectedRead(url, {...options, signal: scopedSignal(options.signal)}, deny);
    const write = (url, options) => {
      if (url !== '/dashboard/fs-home/advisor.json' || options.method !== 'POST') throw Error('observation_endpoint_only');
      return fetch(url, {...options, credentials: 'same-origin', redirect: 'error', signal: scopedSignal(options.signal)}).then(response => {
        if (response.status === 401 || response.status === 403) deny(response.status);
        return response;
      });
    };
    widget = mountDataWorkspace(root, {
      fetch: read, writeFetch: write, start: yesterday, end: yesterday,
      onHermes: identity.role === 'admin' ? payload => location.assign(hermesHandoffURL(payload)) : undefined
    });
    host.dataset.theme = document.documentElement.dataset.fsTheme || 'light';
    host.hidden = false;
    show('按需选择一个工具和日期范围后查询。');
  } catch (error) {
    if (controller.signal.aborted) return;
    if (error.status === 401 || error.status === 403) deny(error.status);
    else show('工具页暂时无法加载，请刷新后重试。', true);
  }
}

theme.value = window.FSTheme?.get() || 'light';
theme.addEventListener('change', () => window.FSTheme?.set(theme.value));
document.addEventListener('fs-theme-change', event => { host.dataset.theme = event.detail.resolved; });
document.addEventListener('visibilitychange', async () => {
  if (document.hidden || !identity || controller.signal.aborted) return;
  try {
    const next = await sessionIdentity(controller.signal);
    if (next.name !== identity.name || next.role !== identity.role || JSON.stringify(next.groups) !== JSON.stringify(identity.groups)) deny(403);
  } catch (error) { if (error.status === 401 || error.status === 403) deny(error.status); }
});
window.addEventListener('pagehide', () => { controller.abort(); widget?.dispose(); });
start();
