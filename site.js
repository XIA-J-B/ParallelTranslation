'use strict';
const root = document.documentElement;
const themeButton = document.querySelector('#theme-toggle');
const previewPicture = document.querySelector('#preview-picture');
const previewPlaceholder = document.querySelector('#reader-preview');
const previewStatus = document.querySelector('#preview-status');
const compactPreview = matchMedia('(max-width: 800px)');
const preparedPreviews = new Map();
let dialogImage = document.querySelector('#dialog-image');
const dialog = document.querySelector('#preview-dialog');
const openPreview = document.querySelector('#open-preview');
const previewScroll = document.querySelector('#preview-scroll');
const previewSize = document.querySelector('#preview-size');
const featureTabs = [...document.querySelectorAll('[data-showcase]')];
const showcase = {
  reader: { title: '对着原文读译文', description: '点击段落，两侧一起定位。翻译运行时，可以先读已完成的部分。', alt: '左侧为英文原文，右侧为中文译文，两栏显示同一篇论文。' },
  annotations: { panelWidth: 540, title: '把疑问写在原句旁', description: '选中文字，在页旁写下批注。下次阅读时，点击批注编号即可回到这段原文。', alt: '论文右侧的批注卡片显示头像、作者、时间和批注内容。' },
  quickread: { panelWidth: 680, title: '先了解论文研究了什么', description: '从研究问题、方法和发现读起，再沿着建议的阅读路线回到正文。', alt: '文章速读面板列出研究问题、方法主线、发现与建议阅读路线。' },
  citation: { panelWidth: 680, title: '带着选中的句子提问', description: '在原文中选取想问的内容，读完回答后，点击引用回到出处。', alt: '助读面板展示与原文选段相关的问题、回答及来源引用。' },
  notes: { panelWidth: 680, title: '把回答和出处一起保存', description: '将有用的回答收藏到阅读笔记，整理时可导出 Markdown。', alt: '阅读笔记面板显示已保存的问答、来源引用与 Markdown 导出按钮。' }
};
let selectedFeature;
let previewTheme = root.dataset.theme;
let galleryNearby = false;
let requestedFrame;
function featureLabel() {
  return document.getElementById(`tab-${selectedFeature}`).textContent;
}
function fullScreenshot(feature, theme) {
  return `assets/${feature}-${theme}.png?v=release-0.1.19`;
}
function preparePreview(feature, priority) {
  const panelWidth = compactPreview.matches && showcase[feature].panelWidth;
  const name = `${feature}${panelWidth ? '-panel' : ''}-${previewTheme}`;
  let frame = preparedPreviews.get(name);
  if (frame) {
    if (priority === 'high') frame.image.fetchPriority = 'high';
    return frame;
  }
  const image = new Image(panelWidth || 1600, panelWidth ? 917 : 1000);
  image.alt = showcase[feature].alt;
  image.decoding = 'async';
  image.fetchPriority = priority;
  image.src = `assets/preview/${name}.webp`;
  frame = { image, ready: false };
  preparedPreviews.set(name, frame);
  frame.loaded = image.decode().catch(() => {
    image.src = `assets/${name}.png?v=release-0.1.19`;
    return image.decode();
  }).then(() => {
    frame.ready = true;
  }, () => {
    if (preparedPreviews.get(name) === frame) preparedPreviews.delete(name);
  });
  return frame;
}
function warmPreviews() {
  if (galleryNearby && !navigator.connection?.saveData) {
    for (const tab of featureTabs) preparePreview(tab.dataset.showcase, 'low');
  }
}
function setPreview(theme) {
  if (theme !== previewTheme) preparedPreviews.clear();
  previewTheme = theme;
  const frame = preparePreview(selectedFeature, 'high');
  const index = featureTabs.findIndex(tab => tab.dataset.showcase === selectedFeature);
  previewPicture.style.setProperty('--preview-strip', `url("assets/preview/strip-${compactPreview.matches ? 'panel-' : ''}${theme}.webp")`);
  previewPicture.style.setProperty('--preview-position', `${index / (featureTabs.length - 1) * 100}%`);
  previewPicture.style.setProperty('--preview-ratio', `${frame.image.getAttribute('width')} / ${frame.image.getAttribute('height')}`);
  requestedFrame = frame;
  previewPlaceholder.width = Number(frame.image.getAttribute('width'));
  previewPlaceholder.height = Number(frame.image.getAttribute('height'));
  previewPlaceholder.alt = frame.image.alt;
  frame.image.id = 'reader-preview';
  // Keep a downloading image detached. Inserting it into a picture can interrupt decode().
  const currentImage = frame.ready ? frame.image : previewPlaceholder;
  if (previewPicture.firstElementChild !== currentImage) previewPicture.replaceChildren(currentImage);
  previewPicture.hidden = false;
  openPreview.classList.remove('preview-unavailable');
  openPreview.setAttribute('aria-busy', String(!frame.ready));
  previewStatus.hidden = frame.ready;
  if (!frame.ready) {
    previewStatus.textContent = `正在载入「${featureLabel()}」清晰图…`;
    frame.loaded.then(() => {
      // A slower download must never replace a newer selection.
      if (requestedFrame !== frame) return;
      openPreview.setAttribute('aria-busy', 'false');
      previewStatus.hidden = frame.ready;
      if (frame.ready) {
        if (previewPicture.firstElementChild !== frame.image) previewPicture.replaceChildren(frame.image);
      } else {
        openPreview.classList.add('preview-unavailable');
        previewStatus.textContent = '清晰预览加载失败，可点击查看完整截图';
      }
    });
  }
  openPreview.href = fullScreenshot(selectedFeature, theme);
  openPreview.setAttribute('aria-label', `查看${featureLabel()}完整截图`);
  document.querySelector('.workbench').dataset.feature = selectedFeature;
  for (const tab of featureTabs) tab.href = fullScreenshot(tab.dataset.showcase, theme);
  document.querySelectorAll('[data-preview-theme]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.previewTheme === theme)));
  warmPreviews();
}
function selectFeature(feature) {
  selectedFeature = feature;
  const item = showcase[feature];
  document.querySelector('#showcase-title').textContent = item.title;
  document.querySelector('#showcase-description').textContent = item.description;
  const tryLink = document.querySelector('#showcase-try');
  const annotation = feature === 'annotations';
  tryLink.href = annotation ? '#annotate-sample' : '#try-reading';
  tryLink.toggleAttribute('data-start-annotation', annotation);
  tryLink.firstChild.textContent = annotation ? '去试写批注 ' : '试读一段 ';
  document.querySelector('#showcase-panel').setAttribute('aria-labelledby', `tab-${feature}`);
  featureTabs.forEach(tab => {
    const active = tab.dataset.showcase === feature;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  setPreview(previewTheme);
}
function activateFeature(tab) {
  selectFeature(tab.dataset.showcase);
  if (location.hash !== `#${tab.id}`) history.pushState(null, '', `#${tab.id}`);
}
function selectLinkedFeature() {
  const tab = featureTabs.find(tab => location.hash === `#${tab.id}`);
  if (tab) selectFeature(tab.dataset.showcase);
  else if (!selectedFeature || !location.hash || location.hash === '#experience') selectFeature('reader');
}
addEventListener('hashchange', selectLinkedFeature);
const showcaseTabs = document.querySelector('.showcase-tabs');
const wideShowcase = matchMedia('(min-width: 1500px)');
function updateShowcaseOrientation() {
  showcaseTabs.setAttribute('aria-orientation', wideShowcase.matches ? 'vertical' : 'horizontal');
}
showcaseTabs.setAttribute('role', 'tablist');
updateShowcaseOrientation();
wideShowcase.addEventListener('change', updateShowcaseOrientation);
document.querySelector('.preview-themes').hidden = false;
const showcasePanel = document.querySelector('#showcase-panel');
showcasePanel.setAttribute('role', 'tabpanel');
showcasePanel.tabIndex = 0;
featureTabs.forEach((tab, index) => {
  tab.setAttribute('role', 'tab');
  tab.setAttribute('aria-controls', 'showcase-panel');
  const prepareTab = () => preparePreview(tab.dataset.showcase, 'high');
  tab.addEventListener('pointerenter', prepareTab);
  tab.addEventListener('focus', prepareTab);
  tab.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    activateFeature(tab);
  });
  tab.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight' || (wideShowcase.matches && event.key === 'ArrowDown')) next = (index + 1) % featureTabs.length;
    if (event.key === 'ArrowLeft' || (wideShowcase.matches && event.key === 'ArrowUp')) next = (index - 1 + featureTabs.length) % featureTabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = featureTabs.length - 1;
    if (event.key === ' ') next = index;
    if (next === undefined) return;
    event.preventDefault();
    activateFeature(featureTabs[next]);
    featureTabs[next].focus();
  });
});
function applyTheme(theme) {
  root.dataset.theme = theme;
  themeButton.setAttribute('aria-label', `切换到${theme === 'dark' ? '浅' : '深'}色主题`);
  themeButton.title = themeButton.getAttribute('aria-label');
  document.querySelector('meta[name="theme-color"]').content = theme === 'dark' ? '#121418' : '#f4f1ea';
}
applyTheme(root.dataset.theme);
themeButton.hidden = false;
selectLinkedFeature();
compactPreview.addEventListener('change', () => {
  preparedPreviews.clear();
  setPreview(previewTheme);
});
if ('IntersectionObserver' in window) {
  const galleryObserver = new IntersectionObserver(([entry]) => {
    galleryNearby = entry.isIntersecting;
    warmPreviews();
  }, { rootMargin: '480px 0px' });
  galleryObserver.observe(document.querySelector('#experience'));
}
themeButton.addEventListener('click', () => {
  const theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(theme);
  setPreview(theme);
  try { localStorage.setItem('parallel-site-theme', theme); } catch {}
});
document.querySelectorAll('[data-preview-theme]').forEach(button => button.addEventListener('click', () => setPreview(button.dataset.previewTheme)));
function setPreviewZoom(original, point) {
  const rect = dialogImage.getBoundingClientRect();
  const panelWidth = showcase[selectedFeature].panelWidth;
  dialog.dataset.original = String(original);
  previewSize.textContent = original ? '适应窗口' : '原始尺寸';
  if (original && point) {
    const x = (point.clientX - rect.left) / rect.width;
    const y = (point.clientY - rect.top) / rect.height;
    previewScroll.scrollTo(x * dialogImage.offsetWidth - previewScroll.clientWidth / 2, y * dialogImage.offsetHeight - previewScroll.clientHeight / 2);
  } else {
    previewScroll.scrollTo(original && panelWidth ? dialogImage.offsetWidth - panelWidth : 0, 0);
  }
}
openPreview.addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || !dialog.showModal) return;
  event.preventDefault();
  if (dialogImage.src !== openPreview.href) {
    const original = new Image(1600, 1000);
    original.id = 'dialog-image';
    original.alt = showcase[selectedFeature].alt;
    const position = previewPicture.style.getPropertyValue('--preview-position');
    original.style.background = `url("assets/preview/strip-${previewTheme}.webp") ${position} top / 500% 100% no-repeat`;
    original.src = openPreview.href;
    dialogImage.replaceWith(original);
    dialogImage = original;
  }
  document.querySelector('#preview-heading').textContent = `${featureLabel()} · ${previewTheme === 'dark' ? '深色' : '浅色'}`;
  dialog.showModal();
  setPreviewZoom(false);
});
previewSize.addEventListener('click', () => setPreviewZoom(dialog.dataset.original !== 'true'));
previewScroll.addEventListener('click', event => {
  if (event.target === dialogImage) setPreviewZoom(dialog.dataset.original !== 'true', event);
});
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

const navToggle = document.querySelector('#nav-toggle');
const navigation = document.querySelector('#site-navigation');
const header = document.querySelector('.site-header');
const compactNav = matchMedia('(max-width: 800px)');
function setMenu(open) {
  navToggle.setAttribute('aria-expanded', String(open));
  header.classList.toggle('menu-open', open);
}
function syncMenu() {
  setMenu(false);
  navToggle.hidden = !compactNav.matches;
  header.classList.toggle('compact-nav', compactNav.matches);
}
navToggle.addEventListener('click', () => setMenu(navToggle.getAttribute('aria-expanded') !== 'true'));
navigation.addEventListener('click', event => {
  const link = event.target.closest('a');
  if (!link || !compactNav.matches) return;
  setMenu(false);
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || navToggle.getAttribute('aria-expanded') !== 'true') return;
  setMenu(false);
  navToggle.focus();
});
document.addEventListener('pointerdown', event => {
  if (!navigation.contains(event.target) && !navToggle.contains(event.target)) setMenu(false);
});
header.addEventListener('focusout', event => {
  if (!header.contains(event.relatedTarget)) setMenu(false);
});
compactNav.addEventListener('change', syncMenu);
syncMenu();
