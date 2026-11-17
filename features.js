'use strict';
(() => {
  const source = document.querySelector('#sample-source');
  const empty = document.querySelector('#sample-empty');
  const answer = document.querySelector('#sample-answer');
  const note = document.querySelector('#sample-note');
  const status = document.querySelector('#sample-status');
  const translation = document.querySelector('#sample-translation');
  const translateButton = document.querySelector('#translate-sample');
  const saveButton = document.querySelector('#save-sample');
  const mark = document.querySelector('#sample-quote mark');
  const annotation = document.querySelector('#sample-annotation');
  const annotationText = document.querySelector('#sample-annotation-text');
  const annotationEditor = document.querySelector('#sample-annotation-editor');
  const annotationInput = document.querySelector('#sample-annotation-input');
  const annotateButton = document.querySelector('#annotate-sample');
  const clearHighlight = document.querySelector('#clear-highlight');
  const colors = { yellow: ['#f3da92', '黄色'], green: ['#b4dfb1', '绿色'], blue: ['#b9d5f5', '蓝色'], pink: ['#f2bed0', '粉色'], purple: ['#d5c2f0', '紫色'] };
  let selectedHighlight = '';
  let reveal;
  const motionAllowed = () => document.documentElement.dataset.motion === 'on';
  function animate(element) {
    reveal?.cancel();
    if (motionAllowed()) reveal = element.animate([{ opacity: 0, transform: 'translateY(9px)' }, { opacity: 1, transform: 'none' }], { duration: 300, easing: 'ease-out' });
  }
  document.addEventListener('parallel-motion-change', event => { if (!event.detail.enabled) reveal?.cancel(); });
  function setHighlight(color) {
    selectedHighlight = color;
    mark.style.setProperty('--sample-highlight', color ? colors[color][0] : 'transparent');
    mark.dataset.highlight = color;
    document.querySelectorAll('[data-highlight]').forEach(button => {
      if (button.tagName === 'BUTTON') button.setAttribute('aria-pressed', String(button.dataset.highlight === color));
    });
    clearHighlight.hidden = !color;
  }
  document.querySelectorAll('button[data-highlight]').forEach(button => button.addEventListener('click', () => {
    setHighlight(button.dataset.highlight);
    status.textContent = `已用${colors[selectedHighlight][1]}标记选段。也可以写下自己的批注。`;
  }));
  clearHighlight.addEventListener('click', () => {
    setHighlight('');
    status.textContent = '已清除选段高亮。';
    document.querySelector('button[data-highlight]').focus();
  });
  function showAnnotationEditor() {
    annotationEditor.hidden = false;
    annotateButton.setAttribute('aria-expanded', 'true');
    annotationInput.value = annotationText.textContent;
    annotationInput.focus();
  }
  function hideAnnotationEditor() {
    annotationEditor.hidden = true;
    annotateButton.setAttribute('aria-expanded', 'false');
  }
  annotateButton.addEventListener('click', showAnnotationEditor);
  document.querySelector('#edit-annotation').addEventListener('click', showAnnotationEditor);
  document.querySelector('#cancel-annotation').addEventListener('click', () => {
    hideAnnotationEditor();
    annotateButton.focus();
  });
  annotationEditor.addEventListener('submit', event => {
    event.preventDefault();
    const text = annotationInput.value.trim();
    if (!text) { annotationInput.focus(); return; }
    annotationText.textContent = text;
    annotation.hidden = false;
    hideAnnotationEditor();
    if (!selectedHighlight) setHighlight('yellow');
    animate(annotation);
    document.querySelector('#locate-annotation').focus({ preventScroll: true });
    status.textContent = '批注已留在当前演示，可编辑或点击回到选段。';
  });
  document.querySelector('#delete-annotation').addEventListener('click', () => {
    annotation.hidden = true;
    annotationText.textContent = '';
    annotationInput.value = '';
    hideAnnotationEditor();
    annotateButton.focus();
    status.textContent = '已删除演示批注。';
  });
  function locateSource() {
    source.classList.add('is-located');
    source.focus({ preventScroll: true });
    source.scrollIntoView({ behavior: motionAllowed() ? 'smooth' : 'instant', block: 'nearest' });
    status.textContent = '已定位示例论文第 5 页的原文选段。';
  }
  document.querySelector('#locate-annotation').addEventListener('click', locateSource);
  translateButton.addEventListener('click', () => {
    translation.hidden = !translation.hidden;
    translateButton.setAttribute('aria-expanded', String(!translation.hidden));
    translateButton.textContent = translation.hidden ? '看看中文' : '收起中文';
  });
  document.querySelector('#explain-sample').addEventListener('click', () => {
    empty.hidden = true;
    answer.hidden = false;
    status.textContent = '已展示预置回答。试试查原文，或收藏为笔记。';
    animate(answer);
    if (innerWidth <= 800) answer.scrollIntoView({ behavior: motionAllowed() ? 'smooth' : 'instant', block: 'nearest' });
  });
  document.querySelector('#sample-citation').addEventListener('click', locateSource);
  saveButton.addEventListener('click', () => {
    note.hidden = false;
    saveButton.textContent = '★ 已加入演示笔记';
    status.textContent = '理解与出处已放进这条演示笔记，可导出 Markdown。';
    animate(note);
  });
  document.querySelector('#export-sample').addEventListener('click', () => {
    const markdown = [
      '# 公平比较的三个条件', '', '> 页间 Parallel 官网交互示例 · 预置教学内容', '',
      '## 问题', '', '怎样才算公平比较？', '',
      '## 理解', '', '先对齐优化目标、任务数据和前馈信息。条件不一致，差距就可能来自实验设置。', '',
      '这是对示例论文的教学归纳，不是现场生成的模型回答。', '',
      '## 原文出处', '', '> Holding equal the optimization objective, data access, and future reference access is imperative to properly evaluate differences in controller synthesis approaches.', '',
      '第 5 页。原文：Leveling the Playing Field: Carefully Comparing Classical and Learned Controllers for Quadrotor Trajectory Tracking（2025）。', '',
      '作者：Pratik Kunapuli、Jake Welde、Dinesh Jayaraman、Vijay Kumar。', '',
      '来源：https://arxiv.org/abs/2506.17832v1', '',
      '许可：CC BY 4.0，https://creativecommons.org/licenses/by/4.0/ 。中文内容为 ParallelTranslation 教学改编，不代表作者背书。', '',
      ...(annotationText.textContent ? ['## 我的批注', '', annotationText.textContent, ''] : []),
      ...(selectedHighlight ? ['## 高亮标记', '', `选段颜色：${colors[selectedHighlight][1]}。`, ''] : [])
    ].join('\n');
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = '页间-示例阅读笔记.md';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status.textContent = '已导出示例笔记 Markdown 文件。';
  });
  document.querySelector('#reset-sample').addEventListener('click', () => {
    reveal?.cancel();
    empty.hidden = false;
    answer.hidden = true;
    note.hidden = true;
    translation.hidden = true;
    source.classList.remove('is-located');
    setHighlight('');
    mark.style.removeProperty('--sample-highlight');
    annotation.hidden = true;
    annotationText.textContent = '';
    annotationInput.value = '';
    hideAnnotationEditor();
    translateButton.setAttribute('aria-expanded', 'false');
    translateButton.textContent = '看看中文';
    saveButton.textContent = '☆ 收藏这条理解';
    status.textContent = '演示已重置。';
  });
})();
