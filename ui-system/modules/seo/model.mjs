export const GAMES = ['FC27', 'D4', 'AION2', 'WOW_FOREVER'];
export class SnapshotClient {
  constructor(read = globalThis.fetch.bind(globalThis)) { this.fetch = read; }
  async get(path, options = {}) {
    const response = await this.fetch('/api/seo/v1/' + path, {credentials: 'same-origin', cache: 'no-store', redirect: 'error', ...options});
    if (!response.ok) throw Error(({401: '请重新登录', 403: '没有当前范围的权限', 404: '尚无已发布数据', 410: '该历史版本已过期', 409: '设置已被其他成员更新，请重新读取'})[response.status] || '读取暂不可用');
    return response.json();
  }
  async init(id) {
    if (id && !/^seo-\d{4}-\d{2}-\d{2}$/.test(id)) throw Error('快照版本无效');
    this.meta = await this.get(id ? `snapshots/${id}/manifest` : 'snapshots/current');
    this.id = this.meta.snapshot_id;
    return this.meta;
  }
  async load(kind, game, cursor = 0) {
    if (!this.id || !this.meta.games.includes(game)) throw Error('游戏范围不可用');
    const result = await this.get(`snapshots/${this.id}/${kind}?` + new URLSearchParams({game, cursor}));
    if (result.snapshot_id !== this.id || result.facts_hash !== this.meta.facts_hash) throw Error('数据版本不一致，请重新打开当前视图');
    return result;
  }
}
export const value = (input, percentage = false) => input == null ? '—' : percentage ? `${(Number(input) * 100).toFixed(1)}%` : Number(input).toLocaleString('zh-CN', {maximumFractionDigits: 2});
