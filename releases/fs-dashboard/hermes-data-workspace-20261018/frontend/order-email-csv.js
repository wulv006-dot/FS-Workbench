/**
 * Serialize an admin_order_email_export.py success payload to a CSV string.
 * The caller owns transport, authorization and saving the UTF-8 string.
 * Completeness is exhausted live pagination, never a point-in-time snapshot.
 * Server trim_casefold deduplication is authoritative: do not approximate
 * Python casefold with JS lowercasing, re-deduplicate, sort or rewrite spelling.
 * Throws TypeError before returning any CSV if the payload is invalid.
 */
export function orderEmailCsv(payload) {
  const fail = () => { throw new TypeError('Invalid or incomplete order email export'); };
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) ||
      payload.complete !== true || payload.status !== 'available' ||
      payload.email_field !== 'user_email' || payload.deduplication !== 'trim_casefold' ||
      payload.semantics !== 'live_non_snapshot' ||
      payload.limitation !== 'live_pagination_not_snapshot' || 'error' in payload) fail();

  const { emails, unique_emails, observed_orders, missing_email_orders, scope } = payload;
  const count = value => Number.isSafeInteger(value) && value >= 0;
  if (!Array.isArray(emails) || !count(unique_emails) || unique_emails !== emails.length ||
      !count(observed_orders) || !count(missing_email_orders) ||
      missing_email_orders > observed_orders ||
      unique_emails > observed_orders - missing_email_orders ||
      (unique_emails === 0 && observed_orders !== missing_email_orders)) fail();
  const id = value => typeof value === 'string' && /^[0-9]{1,20}$/.test(value);
  if (!scope || !id(scope.site_id) || !Array.isArray(scope.game_ids) ||
      scope.game_ids.length < 1 || scope.game_ids.length > 100 ||
      new Set(scope.game_ids).size !== scope.game_ids.length) fail();
  for (const game of scope.game_ids) if (!id(game)) fail();

  // Match the source's permissive email shape, including Unicode and quoted
  // punctuation. Reject invalid entries as a whole, never filter them out.
  for (const email of emails) {
    if (typeof email !== 'string') fail();
    const length = Array.from(email).length;
    const parts = email.split('@');
    if (length < 3 || length > 320 || parts.length !== 2 || !parts[0] || !parts[1] ||
        /[\p{White_Space}\u0000-\u001f\u007f]/u.test(email) ||
        /[\ud800-\udfff]/u.test(email)) fail();
  }
  const cell = email => {
    // CSV quoting alone does not prevent spreadsheet formula evaluation.
    // @-leading values are also guarded here, though source validation rejects them.
    const safe = /^[=+\-@]/.test(email) ? "'" + email : email;
    return '"' + safe.replace(/"/g, '""') + '"';
  };
  return '\uFEFFemail\r\n' + emails.map(email => cell(email) + '\r\n').join('');
}
