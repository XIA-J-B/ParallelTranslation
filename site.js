'use strict';
const root = document.documentElement;
const themeButton = document.querySelector('#theme-toggle');
const previewImage = document.querySelector('#reader-preview');
const dialogImage = document.querySelector('#dialog-image');
const dialog = document.querySelector('#preview-dialog');
const showcase = {
  reader: { title: '原文在旁，译文在眼前。', description: '点一下段落，两边同步定位；翻译没结束，也能先读。', tags: ['同步滚动', '边译边读', '位置记忆'], alt: '真实双语阅读界面：左侧原文，右侧中文译文。' },
  quickread: { title: '先看清主线，再决定深读哪里。', description: '研究问题、方法、发现与局限，先看一遍。', tags: ['文章速读', '阅读路线', '原文引用'], alt: '真实文章速读界面：展示研究问题、方法主线、发现与建议阅读路线。' },
  citation: { title: '看不懂的这一句，直接问。', description: '带着选段追问，从回答里的引用回到原文。', tags: ['选段提问', '上下文解释', '来源回跳'], alt: '真实引用问答界面：带原文引用的问题、回答与左侧高亮的出处。' },
  annotations: { title: '划重点，也记下想法。', description: '五色高亮，写下批注；汇总后一点回看。', tags: ['五色高亮', '文字批注', '原文回跳'], alt: '真实高亮与批注界面：原文黄色高亮、文字批注、批注汇总和编辑操作。' },
  notes: { title: '这次读懂的，下次还在。', description: '收藏有用回答，连同引用一起保存。', tags: ['本地笔记', '保留出处', 'Markdown 导出'], alt: '真实阅读笔记界面：保存的问题、回答、引用与 Markdown 导出按钮。' }
};
let selectedFeature = 'reader';
let previewTheme = 'light';
function setPreview(theme) {
  previewTheme = theme;
  previewImage.src = `assets/${selectedFeature}-${theme}.png`;
  document.querySelector('#reader-mobile-preview').srcset = `assets/${selectedFeature}${selectedFeature === 'reader' ? '' : '-panel'}-${theme}.png`;
  previewImage.alt = showcase[selectedFeature].alt;
  dialogImage.src = previewImage.src;
  dialogImage.alt = previewImage.alt;
  document.querySelector('.workbench').dataset.feature = selectedFeature;
  document.querySelector('#open-preview').setAttribute('aria-label', `放大查看${document.querySelector(`[data-showcase="${selectedFeature}"] strong`).textContent}的真实界面`);
  document.querySelectorAll('[data-preview-theme]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.previewTheme === theme)));
}
function selectFeature(feature) {
  selectedFeature = feature;
  const item = showcase[feature];
  document.querySelector('#showcase-title').textContent = item.title;
  document.querySelector('#showcase-description').textContent = item.description;
  document.querySelector('#showcase-tags').replaceChildren(...item.tags.map(tag => { const span = document.createElement('span'); span.textContent = tag; return span; }));
  document.querySelector('#showcase-panel').setAttribute('aria-labelledby', `tab-${feature}`);
  document.querySelectorAll('[data-showcase]').forEach(tab => {
    const active = tab.dataset.showcase === feature;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  setPreview(previewTheme);
}
const featureTabs = [...document.querySelectorAll('[data-showcase]')];
featureTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectFeature(tab.dataset.showcase));
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % featureTabs.length;
    if (event.key === 'ArrowLeft') next = (index - 1 + featureTabs.length) % featureTabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = featureTabs.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    selectFeature(featureTabs[next].dataset.showcase);
    featureTabs[next].focus();
  });
});
function applyTheme(theme) {
  root.dataset.theme = theme;
  themeButton.setAttribute('aria-label', `切换到${theme === 'dark' ? '浅' : '深'}色主题`);
  themeButton.title = themeButton.getAttribute('aria-label');
  document.querySelector('meta[name="theme-color"]').content = theme === 'dark' ? '#121418' : '#f4f1ea';
  setPreview(theme);
}
applyTheme(root.dataset.theme);
themeButton.addEventListener('click', () => {
  const theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(theme);
  try { localStorage.setItem('parallel-site-theme', theme); } catch {}
});
document.querySelectorAll('[data-preview-theme]').forEach(button => button.addEventListener('click', () => setPreview(button.dataset.previewTheme)));
document.querySelector('#open-preview').addEventListener('click', () => dialog.showModal());
document.querySelector('#close-preview').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
document.querySelector('#copy-checksum').addEventListener('click', async () => {
  const status = document.querySelector('#copy-status');
  try {
    await navigator.clipboard.writeText(document.querySelector('#sha256').textContent);
    status.textContent = '已复制';
  } catch { status.textContent = '请选中上方校验值手动复制'; }
});
document.querySelector('a[href="#attribution"]').addEventListener('click', () => { document.querySelector('#attribution').open = true; });

// Keep the paper's original rotation; motion uses the separate translate property.
const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
const motionButton = document.querySelector('#motion-toggle');
const entranceAnimations = new Set();
let motionPaused = false;
try { motionPaused = localStorage.getItem('parallel-site-motion') === 'off'; } catch {}
function updateMotion() {
  const enabled = !motionPaused && !motionPreference.matches;
  root.dataset.motion = enabled ? 'on' : 'off';
  const label = motionPreference.matches ? '已跟随系统减少动态效果' : enabled ? '暂停网页动效' : '开启网页动效';
  motionButton.setAttribute('aria-label', label);
  motionButton.title = label;
  motionButton.querySelector('span').textContent = motionPreference.matches ? '动效已关闭' : enabled ? '暂停动效' : '开启动效';
  motionButton.disabled = motionPreference.matches;
  motionButton.hidden = false;
  if (!enabled) {
    for (const animation of entranceAnimations) animation.cancel();
    entranceAnimations.clear();
  }
  document.dispatchEvent(new CustomEvent('parallel-motion-change', { detail: { enabled } }));
}
motionButton.addEventListener('click', () => {
  motionPaused = !motionPaused;
  try { localStorage.setItem('parallel-site-motion', motionPaused ? 'off' : 'on'); } catch {}
  updateMotion();
});
motionPreference.addEventListener('change', updateMotion);
updateMotion();

// Animate visible content once, without hiding anything before JS is ready.
if ('IntersectionObserver' in window) {
  const entrances = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entrances.unobserve(entry.target);
      if (root.dataset.motion !== 'on') continue;
      const wide = innerWidth > 800;
      const kind = entry.target;
      let from = 'translateY(38px)';
      if (kind.matches('.workbench')) from = 'perspective(1400px) translateY(60px) rotateX(5deg) scale(.96)';
      if (wide && kind.matches('.capability-card')) from = `translate(${(Array.from(kind.parentElement.children).indexOf(kind) % 3 - 1) * 24}px, 32px)`;
      if (wide && kind.matches('.download-intro')) from = 'translateX(-45px)';
      if (wide && kind.matches('.download-card')) from = 'translateX(45px) rotate(2deg)';
      const animation = entry.target.animate([
        { opacity: 0, transform: from },
        { opacity: 1, transform: 'translateY(0)' }
      ], { duration: kind.matches('.workbench') ? 1050 : 850, delay: Number(entry.target.dataset.motionDelay || 0), easing: 'cubic-bezier(.16,1,.3,1)', fill: 'backwards' });
      entranceAnimations.add(animation);
      animation.finished.then(() => entranceAnimations.delete(animation), () => entranceAnimations.delete(animation));
    }
  }, { threshold: .08 });
  document.querySelectorAll('.capability-card, .steps li').forEach((element, index) => {
    element.dataset.motionDelay = String((index % 3) * 130);
  });
  document.querySelectorAll('.section-heading, .workbench, .sample-workspace, .capability-card, .reading-note, .steps li, .download-intro, .download-card, .faq>div, .footer-top').forEach(element => entrances.observe(element));
  const heroVisibility = new IntersectionObserver(([entry]) => {
    root.dataset.heroVisible = String(entry.isIntersecting);
  });
  heroVisibility.observe(document.querySelector('.hero-art'));
}
function updatePageVisibility() { root.dataset.pageHidden = String(document.hidden); }
document.addEventListener('visibilitychange', updatePageVisibility);
updatePageVisibility();
