'use strict';
(() => {
  const page = document.documentElement;
  const art = document.querySelector('.hero-art');
  const finePointer = matchMedia('(hover: hover) and (pointer: fine) and (min-width: 801px)');
  const animatedButtons = [...document.querySelectorAll('.download-link')];
  const cards = [...document.querySelectorAll('.capability-card')];
  const activeFrames = new Map();
  const enabled = () => page.dataset.motion === 'on' && !document.hidden;

  document.querySelectorAll('.paper .marked').forEach(mark => mark.classList.add('translation-scan', 'motion-ambient'));
  document.querySelectorAll('.steps li').forEach(step => step.classList.add('step-trace'));

  function schedule(target, work) {
    if (activeFrames.has(target)) cancelAnimationFrame(activeFrames.get(target));
    activeFrames.set(target, requestAnimationFrame(() => {
      activeFrames.delete(target);
      if (enabled()) work();
    }));
  }
  function reset(target, properties) {
    if (activeFrames.has(target)) cancelAnimationFrame(activeFrames.get(target));
    activeFrames.delete(target);
    properties.forEach(name => target.style.removeProperty(name));
  }
  const tiltProperties = ['--tilt-x', '--tilt-y', '--field-x', '--field-y'];
  art.addEventListener('pointermove', event => {
    if (!enabled() || !finePointer.matches || event.pointerType === 'touch') return;
    const bounds = art.getBoundingClientRect();
    const x = Math.max(-1, Math.min(1, (event.clientX - bounds.left) / bounds.width * 2 - 1));
    const y = Math.max(-1, Math.min(1, (event.clientY - bounds.top) / bounds.height * 2 - 1));
    schedule(art, () => {
      art.style.setProperty('--tilt-x', `${-y * 7}deg`);
      art.style.setProperty('--tilt-y', `${x * 9}deg`);
      art.style.setProperty('--field-x', `${x * -14}px`);
      art.style.setProperty('--field-y', `${y * -12}px`);
    });
  });
  art.addEventListener('pointerleave', () => reset(art, tiltProperties));

  animatedButtons.forEach(button => {
    button.addEventListener('pointermove', event => {
      if (!enabled() || !finePointer.matches || event.pointerType === 'touch') return;
      const bounds = button.getBoundingClientRect();
      schedule(button, () => {
        button.style.setProperty('--magnet-x', `${((event.clientX - bounds.left) / bounds.width - .5) * 8}px`);
        button.style.setProperty('--magnet-y', `${((event.clientY - bounds.top) / bounds.height - .5) * 6}px`);
      });
    });
    button.addEventListener('pointerleave', () => reset(button, ['--magnet-x', '--magnet-y']));
  });

  document.querySelectorAll('.button').forEach(button => {
    button.addEventListener('pointerdown', event => {
      if (!enabled() || event.button !== 0) return;
      button.querySelector('.click-wave')?.remove();
      const bounds = button.getBoundingClientRect();
      const ripple = document.createElement('span');
      ripple.className = 'click-wave';
      ripple.setAttribute('aria-hidden', 'true');
      ripple.style.left = `${event.clientX - bounds.left}px`;
      ripple.style.top = `${event.clientY - bounds.top}px`;
      button.append(ripple);
      setTimeout(() => ripple.remove(), 650);
    });
  });

  cards.forEach(card => {
    card.addEventListener('pointermove', event => {
      if (!enabled() || !finePointer.matches) return;
      const bounds = card.getBoundingClientRect();
      schedule(card, () => {
        card.style.setProperty('--spot-x', `${event.clientX - bounds.left}px`);
        card.style.setProperty('--spot-y', `${event.clientY - bounds.top}px`);
      });
    });
    card.addEventListener('pointerleave', () => reset(card, ['--spot-x', '--spot-y']));
  });

  function resetInteraction() {
    if (enabled() && finePointer.matches) return;
    reset(art, tiltProperties);
    animatedButtons.forEach(button => reset(button, ['--magnet-x', '--magnet-y']));
    cards.forEach(card => reset(card, ['--spot-x', '--spot-y']));
    document.querySelectorAll('.click-wave').forEach(ripple => ripple.remove());
  }
  document.addEventListener('parallel-motion-change', resetInteraction);
  document.addEventListener('visibilitychange', resetInteraction);
  finePointer.addEventListener('change', resetInteraction);
  resetInteraction();

  if ('IntersectionObserver' in window) {
    const visibility = new IntersectionObserver(entries => {
      entries.forEach(entry => { entry.target.dataset.richVisible = String(entry.isIntersecting); });
    });
    document.querySelectorAll('.hero-art, .feature-visual, .steps, .download-section, .download-link').forEach(element => visibility.observe(element));
  }
})();
