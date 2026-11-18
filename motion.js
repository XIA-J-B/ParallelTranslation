'use strict';
(() => {
  const root = document.documentElement;
  const toggle = document.querySelector('#motion-toggle');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const targets = document.querySelectorAll([
    '.hero-copy', '.reader-plate', '.section-heading', '.showcase-summary', '.workbench',
    '.reading-lab', '.capability-card', '.reading-note', '.steps li', '.download-intro',
    '.download-card', '#faq > div:first-child', '.faq-list details', '.footer-top'
  ].join(','));
  let entryObserver, exitObserver;
  let lastY = window.scrollY;
  let direction = 'down';
  let paused = false;
  try { paused = localStorage.getItem('parallel-site-motion') === 'off'; } catch {}

  function trackDirection() {
    const y = window.scrollY;
    if (y !== lastY) direction = y > lastY ? 'down' : 'up';
    lastY = y;
  }

  function observeEntrances(enabled) {
    if (!('IntersectionObserver' in window)) return;
    if (!enabled) {
      entryObserver?.disconnect();
      exitObserver?.disconnect();
      window.removeEventListener('scroll', trackDirection);
      for (const target of targets) delete target.dataset.motionEnter;
      return;
    }
    lastY = window.scrollY;
    window.addEventListener('scroll', trackDirection, { passive: true });
    const header = document.querySelector('.site-header');
    const topInset = getComputedStyle(header).position === 'sticky' ? header.offsetHeight : 0;
    entryObserver = new IntersectionObserver(entries => {
      trackDirection();
      for (const { target, isIntersecting } of entries) {
        if (isIntersecting && !target.hasAttribute('data-motion-enter')) target.dataset.motionEnter = direction;
      }
    }, { rootMargin: `-${topInset + 32}px 0px -32px` });
    // Rearm beyond a separate outer edge so a small scroll reversal cannot restart an entrance.
    exitObserver = new IntersectionObserver(entries => {
      for (const { target, isIntersecting } of entries) {
        if (!isIntersecting) delete target.dataset.motionEnter;
      }
    }, { rootMargin: `${8 - topInset}px 0px 8px` });
    for (const target of targets) {
      entryObserver.observe(target);
      exitObserver.observe(target);
    }
  }

  function updateMotion() {
    const enabled = !paused && !reducedMotion.matches;
    root.dataset.motion = enabled ? 'on' : 'off';
    const label = reducedMotion.matches ? '已跟随系统减少动态效果' : enabled ? '暂停网页动效' : '开启网页动效';
    toggle.setAttribute('aria-label', label);
    toggle.title = label;
    toggle.querySelector('span').textContent = reducedMotion.matches ? '动效已关闭' : enabled ? '暂停动效' : '开启动效';
    toggle.disabled = reducedMotion.matches;
    toggle.hidden = false;
    observeEntrances(enabled);
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
