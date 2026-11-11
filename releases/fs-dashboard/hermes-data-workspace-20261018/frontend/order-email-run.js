/** Pure, in-memory traversal. The caller owns HTTP, retries and restart policy.
 * Call nextRequest(), POST that body, then acceptPage(parsedBody). On transport
 * failure call nextRequest() again. Never accept an old response after restart.
 * No persistence: clear() permanently cancels this instance and erases its PII.
 */
const DAY = 86400000;
const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const text = v => typeof v === 'string' && v.trim().length > 0;
const count = v => Number.isSafeInteger(v) && v >= 0;
const id = v => typeof v === 'string' && /^[0-9]{1,20}$/.test(v);
const exactKeys = (v, keys) => object(v) && Object.keys(v).length === keys.length &&
  keys.every(k => Object.hasOwn(v, k));
const requireValid = ok => { if (!ok) throw new TypeError('Invalid order email traversal data'); };
function date(value) {
  requireValid(typeof value === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value));
  const time = Date.parse(value + 'T00:00:00Z');
  requireValid(Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value &&
    value.slice(0, 4) !== '0000');
  return time;
}

/** Validate an annual request and return fresh game-major, <=28-day bodies. */
export function buildOrderEmailRequests(input) {
  requireValid(exactKeys(input, ['site_id', 'game_ids', 'start', 'end_exclusive']));
  requireValid(id(input.site_id) && Array.isArray(input.game_ids) &&
    input.game_ids.length > 0 && input.game_ids.length <= 100 &&
    Array.from(input.game_ids).every(id) && new Set(input.game_ids).size === input.game_ids.length);
  const start = date(input.start), end = date(input.end_exclusive);
  requireValid(end > start && end - start <= 366 * DAY);
  const requests = [];
  for (const game_id of input.game_ids) {
    for (let t = start; t < end; t += 28 * DAY) requests.push({
      site_id: input.site_id, game_id,
      start: new Date(t).toISOString().slice(0, 10),
      end_exclusive: new Date(Math.min(t + 28 * DAY, end)).toISOString().slice(0, 10),
    });
  }
  return requests;
}

export class OrderEmailRun {
  #requests; #scope; #period;
  #state = 'active'; #index = 0; #pending = false; #cursor = null;
  #cursors = new Set(); #ids = new Set(); #emails = new Map();
  #total = null; #rows = 0; #orders = 0; #missing = 0; #unique = 0; #pages = 0;
  #reported = 0;

  constructor(input) {
    this.#requests = buildOrderEmailRequests(input);
    this.#scope = { site_id: input.site_id, game_ids: [...input.game_ids] };
    this.#period = { start: input.start, end_exclusive: input.end_exclusive };
  }

  nextRequest() {
    if (this.#state === 'exhausted') return null;
    requireValid(this.#state === 'active');
    this.#pending = true;
    return { ...this.#requests[this.#index],
      ...(this.#cursor === null ? {} : { cursor: this.#cursor }) };
  }

  /** Invalid pages permanently invalidate the run. Nothing from them commits.
   * Totals are stable per game/window, IDs are unique across the entire run.
   * Python-produced email_key is opaque: never normalize it in JavaScript.
   */
  acceptPage(payload) {
    try {
      requireValid(this.#state === 'active' && this.#pending);
      const request = this.#requests[this.#index];
      requireValid(object(payload) && !('error' in payload) &&
        payload.status === 'partial' && payload.complete === false &&
        payload.semantics === 'live_non_snapshot' &&
        payload.limitation === 'live_pagination_not_snapshot' &&
        payload.timezone === 'Asia/Shanghai' && payload.date_field === 'paytime' &&
        payload.email_field === 'user_email' && payload.deduplication === 'trim_casefold' &&
        text(payload.observed_at));
      requireValid(exactKeys(payload.scope, ['site_id', 'game_id']) &&
        payload.scope.site_id === request.site_id && payload.scope.game_id === request.game_id &&
        exactKeys(payload.period, ['start', 'end_exclusive']) &&
        payload.period.start === request.start && payload.period.end_exclusive === request.end_exclusive);
      const total = payload.source_reported_total, rows = payload.data;
      requireValid(count(total) && (this.#total === null || total === this.#total) &&
        Array.isArray(rows) && count(payload.observed_page_rows) &&
        rows.length === payload.observed_page_rows && rows.length <= 20);
      const cursor = payload.next_cursor;
      requireValid(cursor === null || (text(cursor) && !this.#cursors.has(cursor)));
      const received = this.#rows + rows.length;
      requireValid(received <= total && (cursor === null ? received === total : received < total));
      requireValid(rows.length > 0 || (total === 0 && this.#rows === 0 && cursor === null));
      const pageIds = new Set(), pageEmails = new Map();
      let missing = 0;
      for (const row of rows) {
        requireValid(exactKeys(row, ['order_id', 'email', 'email_key']) && text(row.order_id) &&
          !this.#ids.has(row.order_id) && !pageIds.has(row.order_id));
        pageIds.add(row.order_id);
        if (row.email === null) {
          requireValid(row.email_key === null);
          missing++;
        } else {
          requireValid(text(row.email) && text(row.email_key));
          if (!pageEmails.has(row.email_key)) pageEmails.set(row.email_key, row.email);
        }
      }
      requireValid(Number.isSafeInteger(this.#orders + rows.length) &&
        Number.isSafeInteger(this.#reported + (cursor === null ? total : 0)));
      // Commit only after the entire envelope, traversal and final row validate.
      for (const orderId of pageIds) this.#ids.add(orderId);
      for (const [key, email] of pageEmails) if (!this.#emails.has(key)) this.#emails.set(key, email);
      this.#unique = this.#emails.size;
      this.#missing += missing;
      this.#orders += rows.length;
      this.#pages++;
      this.#total = total;
      this.#rows = received;
      this.#cursor = cursor;
      this.#pending = false;
      if (cursor !== null) this.#cursors.add(cursor);
      else {
        this.#reported += total;
        this.#index++;
        this.#total = null;
        this.#rows = 0;
        this.#cursors.clear();
        if (this.#index === this.#requests.length) this.#state = 'exhausted';
      }
    } catch (error) {
      this.#state = 'invalid';
      this.#erase();
      throw error;
    }
    return this.snapshot();
  }

  /** Progress only: no emails, order IDs or opaque cursor tokens. */
  snapshot() {
    return { state: this.#state, traversal_exhausted: this.#state === 'exhausted', complete: false,
      total_windows: this.#requests.length, exhausted_windows: this.#index,
      accepted_pages: this.#pages, observed_orders: this.#orders,
      missing_email_orders: this.#missing, unique_emails: this.#unique };
  }

  result() {
    requireValid(this.#state === 'exhausted' && this.#orders === this.#reported);
    return { ...this.snapshot(), semantics: 'live_non_snapshot',
      limitation: 'live_pagination_not_snapshot', timezone: 'Asia/Shanghai',
      date_field: 'paytime', email_field: 'user_email', deduplication: 'trim_casefold',
      source_reported_total: this.#reported, emails: [...this.#emails.values()],
      scope: { ...this.#scope, game_ids: [...this.#scope.game_ids] }, period: { ...this.#period } };
  }

  #erase() {
    this.#ids.clear(); this.#emails.clear(); this.#cursors.clear();
    this.#cursor = null; this.#pending = false;
  }

  clear() {
    this.#erase();
    this.#state = 'cleared';
    this.#index = this.#rows = this.#orders = this.#missing = this.#unique = this.#pages = this.#reported = 0;
    this.#total = null;
  }
}
