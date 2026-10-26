const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const code = ts.transpileModule(
  fs.readFileSync(path.join(__dirname, '../lib/reportDates.ts'), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } },
).outputText;
const context = { exports: {} };
vm.runInNewContext(code, context);
const defaults = { startDate: '2025-10-26', endDate: '2026-10-26' };
function dates(query) {
  return JSON.parse(JSON.stringify(context.exports.initialReportDates(new URLSearchParams(query), defaults)));
}

test('direct report entry keeps its one-year default', () => {
  assert.deepEqual(dates(''), { ...defaults, preset: '1yr' });
});

test('redirected calendar dates initialize the location report without activating a default preset', () => {
  assert.deepEqual(dates('start_date=2024-02-29&end_date=2024-12-31'), {
    startDate: '2024-02-29', endDate: '2024-12-31', preset: null,
  });
  assert.deepEqual(dates('start_date=2023-01-01'), {
    startDate: '2023-01-01', endDate: defaults.endDate, preset: null,
  });
});

test('explicit empty date bounds stay open', () => {
  assert.deepEqual(dates('start_date=&end_date='), { startDate: '', endDate: '', preset: null });
  assert.deepEqual(dates('end_date='), { startDate: defaults.startDate, endDate: '', preset: null });
});

test('invalid dates do not roll into another month or escape the supported calendar', () => {
  for (const invalid of ['2023-02-29', '2024-02-30', '2024-13-01', '0000-01-01', '10000-01-01', '2024-1-1', 'yesterday', '2024-01-01T00:00:00Z']) {
    assert.deepEqual(dates(`start_date=${encodeURIComponent(invalid)}&end_date=2024-12-31`), {
      startDate: defaults.startDate, endDate: '2024-12-31', preset: null,
    }, invalid);
  }
});
