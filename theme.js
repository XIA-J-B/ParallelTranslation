(() => {
  let theme = 'light';
  try { theme = localStorage.getItem('parallel-site-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); } catch {}
  document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
  let motionPaused = false;
  try { motionPaused = localStorage.getItem('parallel-site-motion') === 'off'; } catch {}
  document.documentElement.dataset.motion = motionPaused || matchMedia('(prefers-reduced-motion: reduce)').matches ? 'off' : 'on';
})();
