import test from 'node:test';
import assert from 'node:assert/strict';
import { parseArgs, planFromScout } from '../ops/smartscore_upcoming_cdp.mjs';

test('Hermes shortlist drives at most one query per home team', () => {
  const now = Date.parse('2026-11-15T10:10:00Z');
  const plan = planFromScout({
    generated_at_utc: '2026-11-15T10:00:00Z',
    matches: [
      { home: 'Spain', away: 'England', date: '2026-11-15' },
      { home: '1. FC Köln', away: 'Bayern Munich', date: '2026-11-16' },
    ],
  }, now);
  assert.deepEqual(plan.teams, ['Spain', '1. FC Köln']);
  assert.equal(plan.fixtureKeys.Spain, '2026-11-15:Spain:England');
  assert.throws(() => planFromScout({
    generated_at_utc: '2026-11-15T04:00:00Z',
    matches: [{ home: 'Spain', away: 'England', date: '2026-11-15' }],
  }, now), /stale/);
  assert.throws(() => planFromScout({
    generated_at_utc: '2026-11-15T10:00:00Z',
    matches: [{ home: '@everyone', away: 'England', date: '2026-11-15' }],
  }, now), /Invalid team/);
});

test('official destination and sending must be explicit', () => {
  assert.deepEqual(parseArgs([]), {
    target: 'test', team: undefined, scoutFile: undefined, send: false, navigate: false,
  });
  assert.equal(parseArgs(['--target', 'official', '--team', 'Spain', '--send']).send, true);
  assert.throws(() => parseArgs(['--target', 'other']), /Target/);
  assert.throws(() => parseArgs(['--team', 'Spain', '--scout-file', 'x']), /Choose/);
});
