'use strict';
function publicURL(env) {
  if (!env.CAMPAIGN_PUBLIC_ORIGIN) {
    if (env.CAMPAIGN_PUBLIC_PREFIX) throw new Error('CAMPAIGN_PUBLIC_ORIGIN is required with a public prefix');
    return '';
  }
  const origin = new URL(env.CAMPAIGN_PUBLIC_ORIGIN);
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.origin !== env.CAMPAIGN_PUBLIC_ORIGIN) throw new Error('Public origin must be an exact HTTPS origin');
  const prefix = env.CAMPAIGN_PUBLIC_PREFIX || '/events/';
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(prefix)) throw new Error('Public prefix must be a slash-delimited path');
  return origin.origin + prefix + 'seasonal/';
}
module.exports = {publicURL};
