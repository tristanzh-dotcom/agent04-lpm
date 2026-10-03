import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { test } from 'node:test';

test('only the same-origin parent can request a search through the published shell', async () => {
  const source = await readFile(new URL('../frontend/agent04/app.js', import.meta.url), 'utf8');
  const start = source.indexOf('  window.addEventListener("message", (event) => {');
  const script = source.slice(start, source.indexOf('\n\n  function setFaceStatus', start));
  const parent = {};
  let message;
  const searches = [];
  const window = { parent, location: { origin: 'http://127.0.0.1:3000' }, addEventListener: (_type, fn) => { message = fn; } };
  vm.runInNewContext(script, { window, switchPanel() {}, runSearchFromShell: query => searches.push(query) });
  const data = { type: 'agent04:run-search', query: 'test query' };
  message({ origin: 'https://untrusted.invalid', source: parent, data });
  message({ origin: window.location.origin, source: {}, data });
  assert.equal(searches.length, 0);
  message({ origin: window.location.origin, source: parent, data });
  assert.deepEqual(searches, ['test query']);
});
