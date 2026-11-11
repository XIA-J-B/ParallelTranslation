'use strict';
// Interface theme: follow the system, or force light/dark. The head script in
// index.html applies a saved choice before the stylesheet paints.
(() => {
  const KEY = 'parallel-theme', CHOICES = ['system', 'light', 'dark'];
  const LABELS = {system: '跟随系统', light: '浅色', dark: '深色'};
  const root = document.documentElement;
  function read() {
    try { const value = JSON.parse(localStorage.getItem(KEY)); return CHOICES.includes(value) ? value : 'system'; }
    catch { return 'system'; }
  }
  function apply(choice) {
    if (choice === 'system') delete root.dataset.theme; else root.dataset.theme = choice;
    root.dataset.themeChoice = choice;
    const toggle = document.querySelector('#theme-toggle'), select = document.querySelector('#theme-select');
    if (toggle) {
      const label = `界面颜色：${LABELS[choice]}（点击切换）`;
      toggle.setAttribute('aria-label', label); toggle.title = label;
    }
    if (select) select.value = choice;
  }
  function choose(choice) {
    apply(choice);
    try { localStorage.setItem(KEY, JSON.stringify(choice)); } catch { /* The choice still applies to this page. */ }
  }
  apply(read());
  document.querySelector('#theme-toggle')?.addEventListener('click', () => {
    const current = root.dataset.themeChoice || 'system';
    choose(CHOICES[(CHOICES.indexOf(current) + 1) % CHOICES.length]);
  });
  document.querySelector('#theme-select')?.addEventListener('change', event => choose(event.target.value));
})();
