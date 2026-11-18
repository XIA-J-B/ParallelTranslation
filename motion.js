'use strict';
(() => {
  const root = document.documentElement;
  const toggle = document.querySelector('#motion-toggle');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false;
  try { paused = localStorage.getItem('parallel-site-motion') === 'off'; } catch {}

  function updateMotion() {
    const enabled = !paused && !reducedMotion.matches;
    root.dataset.motion = enabled ? 'on' : 'off';
    const label = reducedMotion.matches ? '已跟随系统减少动态效果' : enabled ? '暂停网页动效' : '开启网页动效';
    toggle.setAttribute('aria-label', label);
    toggle.title = label;
    toggle.querySelector('span').textContent = reducedMotion.matches ? '动效已关闭' : enabled ? '暂停动效' : '开启动效';
    toggle.disabled = reducedMotion.matches;
    toggle.hidden = false;
    document.dispatchEvent(new CustomEvent('parallel-motion-change', { detail: { enabled } }));
  }

  toggle.addEventListener('click', () => {
    paused = !paused;
    try { localStorage.setItem('parallel-site-motion', paused ? 'off' : 'on'); } catch {}
    updateMotion();
  });
  reducedMotion.addEventListener('change', updateMotion);
  updateMotion();
})();
