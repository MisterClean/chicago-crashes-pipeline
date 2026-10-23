const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function ui() {
  const elements = new Map();
  const document = {
    addEventListener() {},
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { innerHTML: '', textContent: '', appendChild() {}, addEventListener() {}, classList: { add() {}, remove() {} } });
      return elements.get(id);
    },
    createElement() { return {}; },
  };
  const context = { document, window: { location: { pathname: '/admin/' }, addEventListener() {} }, console, setInterval() {}, clearInterval() {} };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/admin/app.js'), 'utf8'), context);
  return { context, elements, document };
}
test('uploaded labels, filenames and feature properties render as text', () => {
  const { context, document } = ui();
  const value = '<img src=x onerror="steal()">';
  const layer = { id: 4, name: value, description: value, original_filename: value, geometry_type: 'Polygon', srid: 4326, feature_count: 1, is_active: true, label_field: value, sort_type: 'alphabetic', fields: ['name'], feature_samples: [{ id: 10, properties: { name: value } }] };
  context.displaySpatialLayers([layer]);
  assert.ok(document.getElementById('spatial-layer-table-body').innerHTML.includes('&lt;img'));
  assert.ok(!document.getElementById('spatial-layer-table-body').innerHTML.includes('<img'));
  context.populateSpatialLayerModal(layer);
  assert.ok(document.getElementById('spatial-layer-meta').innerHTML.includes('&lt;img'));
  assert.ok(document.getElementById('spatial-layer-samples').innerHTML.includes('&lt;img'));
  assert.ok(!document.getElementById('spatial-layer-samples').innerHTML.includes('<img'));
});

test('admin requests use the shared proxy path and keep credentials in headers', async () => {
  const { context } = ui();
  const requests = [];
  context.sessionStorage = { getItem() { return 'local-test-key'; } };
  context.FormData = class {};
  context.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ total_jobs: 0 }), { status: 200 });
  };
  await context.apiRequest('/jobs/summary');
  assert.equal(requests[0].url, '/admin/api/jobs/summary');
  assert.equal(requests[0].options.headers['X-API-Key'], 'local-test-key');
  assert.equal(requests[0].url.includes('local-test-key'), false);
});
