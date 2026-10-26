const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = path.join(__dirname, '..');
const nativeRequire = createRequire(path.join(root, 'package.json'));
const modules = new Map();
function load(file) {
  if (modules.has(file)) return modules.get(file);
  const exports = {};
  modules.set(file, exports);
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(code, { exports, require: (specifier) => {
    if (!specifier.startsWith('.') && !specifier.startsWith('@/')) return nativeRequire(specifier);
    const resolved = specifier.startsWith('@/') ? path.join(root, specifier.slice(2)) : path.resolve(path.dirname(file), specifier);
    const target = ['.ts', '.tsx'].map(ext => resolved + ext).find(fs.existsSync);
    return load(target);
  } }, { filename: file });
  return exports;
}
const { formatCost, costBasisLabel } = load(path.join(root, 'lib/costDisplay.ts'));
const { CostBreakdownTable } = load(path.join(root, 'app/dashboard/location-report/components/CostBreakdownTable.tsx'));
const { ReportStats } = load(path.join(root, 'app/dashboard/location-report/components/ReportStats.tsx'));
const coverage = (status = 'complete') => ({
  status, crash_count: 1, complete_crashes: status === 'complete' ? 1 : 0,
  partial_crashes: status === 'partial' ? 1 : 0, unavailable_crashes: status === 'unavailable' ? 1 : 0,
  unknown_injury_count: 0, missing_people_crashes: 0, missing_vehicle_crashes: 0,
  inconsistent_injury_crashes: 0, inconsistent_vehicle_crashes: 0,
});
function year(year, status = 'complete') {
  const supported = status !== 'unavailable';
  return {
    year, crash_count: 1, coverage: coverage(status),
    injury_costs: [{ classification: 'FATAL', classification_label: 'Fatal (K)', count: 1, priced_count: supported ? 1 : 0,
      unit_economic_cost: supported ? year : null, unit_qaly_cost: supported ? 1000 : null,
      subtotal_economic: supported ? year : null, subtotal_societal: supported ? year + 1000 : null }],
    vehicle_costs: { count: 1, priced_count: supported ? 1 : 0, unit_economic_cost: supported ? 100 : null,
      unit_qaly_cost: supported ? 0 : null, subtotal_economic: supported ? 100 : null, subtotal_societal: supported ? 100 : null },
    total_economic: supported ? year + 100 : null, total_societal: supported ? year + 1100 : null,
  };
}
function breakdown(years) {
  const first = years[0];
  return {
    ...first, years, methodology: { version: 'fixture-v1', base_dollar_year: 2019, publication_year: 2025,
      source_url: 'https://highways.dot.gov/fixture', supported_years: [2023, 2024],
      annual_inputs: [{ year: 2023, cpi: 304.702, muwe: 1115.75 }, { year: 2024, cpi: 313.689, muwe: 1159.75 }] },
    injury_costs: first.injury_costs.map(row => ({ ...row, unit_economic_cost: years.length > 1 ? null : row.unit_economic_cost,
      unit_qaly_cost: years.length > 1 ? null : row.unit_qaly_cost })),
  };
}
function render(Component, props) {
  return renderToStaticMarkup(React.createElement(Component, props));
}
test('unavailable money is never formatted as zero, while a genuine zero remains $0', () => {
  assert.equal(formatCost(null), 'Unavailable');
  assert.equal(formatCost(undefined), 'Unavailable');
  assert.equal(formatCost(0), '$0');
});
test('multi-year breakdown shows nominal basis and distinct expandable annual rates', () => {
  const report = breakdown([year(2023), year(2024)]);
  const html = render(CostBreakdownTable, { breakdown: report });
  assert.equal(costBasisLabel(report), 'Sum of crash-year nominal dollars');
  assert.match(html, /Varies by year/);
  assert.match(html, /2023: unit rates and classification detail/);
  assert.match(html, /2024: unit rates and classification detail/);
  assert.match(html, /\$2,023/);
  assert.match(html, /\$2,024/);
  assert.match(html, /not adjusted to a common year/);
  assert.match(html, /does not prove the source has published every record/);
});
test('unsupported year displays unavailable estimates and zero priced records', () => {
  const html = render(CostBreakdownTable, { breakdown: breakdown([year(2025, 'unavailable')]) });
  assert.match(html, /Cost estimate unavailable/);
  assert.match(html, /0 \/ 1/);
  assert.match(html, /Unavailable/);
  assert.doesNotMatch(html, /\$0/);
});
test('headline totals clearly identify partial estimates and disclose missing components', () => {
  const costs = breakdown([year(2024, 'partial')]);
  costs.coverage.unknown_injury_count = 2;
  costs.coverage.inconsistent_vehicle_crashes = 1;
  const stats = { total_crashes: 1, total_fatalities: 0, incapacitating_injuries: 0, total_injuries: 1,
    pedestrians_involved: 0, cyclists_involved: 0, children_injured: 0, hit_and_run_count: 0,
    crashes_with_injuries: 1, crashes_with_fatalities: 0, total_vehicles: 1, unknown_injury_count: 2,
    estimated_economic_damages: costs.total_economic, estimated_societal_costs: costs.total_societal, cost_breakdown: costs };
  const html = render(ReportStats, { stats });
  assert.match(html, /Partial Economic Cost/);
  assert.match(html, /Partial Societal Cost/);
  assert.match(html, /known costs only/);
  assert.match(html, /2 people with unknown injury classifications/);
  assert.match(html, /1 crashes with inconsistent vehicle counts/);
  assert.match(html, /unavailable costs are not treated as zero/);
});
