'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const script = fs.readFileSync(require.resolve('../static/theme.js'), 'utf8');

function page(storage, blocked = false) {
  const root = {dataset: {}}, listeners = {}, attributes = {};
  const toggle = {setAttribute: (key, value) => attributes[key] = value,
    addEventListener: (name, fn) => listeners['toggle:' + name] = fn};
  const select = {value: '', addEventListener: (name, fn) => listeners['select:' + name] = fn};
  const context = vm.createContext({document: {documentElement: root,
    querySelector: query => query === '#theme-toggle' ? toggle : query === '#theme-select' ? select : null},
    localStorage: {getItem(key) { if (blocked) throw new Error('Storage unavailable'); return storage[key] ?? null; },
      setItem(key, value) { if (blocked) throw new Error('Storage unavailable'); storage[key] = value; }}});
  vm.runInContext(script, context);
  return {root, toggle, select, attributes, listeners};
}

test('explicit light and dark preferences persist across reloads with accessible controls', () => {
  const storage = {};
  const first = page(storage);
  assert.equal(first.root.dataset.theme, undefined);
  assert.equal(first.root.dataset.themeChoice, 'system');
  first.listeners['toggle:click']();
  assert.equal(first.root.dataset.theme, 'light');
  assert.match(first.attributes['aria-label'], /浅色/);
  const reloaded = page(storage);
  assert.equal(reloaded.select.value, 'light');
  reloaded.listeners['select:change']({target: {value: 'dark'}});
  assert.equal(reloaded.root.dataset.theme, 'dark');
  assert.match(reloaded.toggle.title, /深色/);
  assert.equal(page(storage).root.dataset.theme, 'dark');
});

test('returning to system mode removes the forced theme for live OS preferences', () => {
  const storage = {'parallel-theme': JSON.stringify('dark')};
  const current = page(storage);
  current.listeners['toggle:click']();
  assert.equal(current.root.dataset.theme, undefined);
  assert.equal(current.root.dataset.themeChoice, 'system');
  assert.equal(current.select.value, 'system');
  assert.equal(JSON.parse(storage['parallel-theme']), 'system');
});

test('corrupt or unavailable browser storage still permits in-page theme changes', () => {
  for (const saved of ['{broken', JSON.stringify('unknown'), JSON.stringify({theme: 'dark'})]) {
    const current = page({'parallel-theme': saved});
    assert.equal(current.root.dataset.themeChoice, 'system');
    assert.equal(current.root.dataset.theme, undefined);
  }
  const current = page({}, true);
  current.listeners['select:change']({target: {value: 'dark'}});
  assert.equal(current.root.dataset.theme, 'dark');
  assert.equal(current.select.value, 'dark');
});
