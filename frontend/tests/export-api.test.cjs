const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const code = ts.transpileModule(fs.readFileSync(require('node:path').join(__dirname, '../lib/api.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
function load(fetch) {
  const context = { exports: {}, process: { env: {} }, window: {}, fetch, setTimeout: (fn) => fn(), Date };
  vm.runInNewContext(code, context);
  return context.exports;
}
test('exports reject an invalid API key with actionable text', async () => {
  const api = load(async () => ({ status: 401, ok: false }));
  await assert.rejects(api.exportLocationReport({ datasets: ['crashes'] }, 'invalid'), /requires a valid API key/);
});
test('exports poll with header authentication and return direct bucket URL without reading a Blob', async () => {
  const requests = [];
  const responses = [{ id: 'job', status: 'queued' }, { id: 'job', status: 'completed' }, { url: 'https://bucket.example/file?signature=test' }];
  const api = load(async (url, options) => { requests.push({ url, options }); return { ok: true, status: 200, json: async () => responses.shift() }; });
  assert.equal(await api.exportLocationReport({ datasets: ['crashes'] }, 'secret'), 'https://bucket.example/file?signature=test');
  assert.equal(requests.length, 3);
  for (const request of requests) {
    assert.equal(request.options.headers['X-API-Key'], 'secret');
    assert.equal(request.url.includes('secret'), false);
  }
});
