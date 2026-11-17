'use strict';
(() => {
  const samples = [
    { id: 'fairness', label: '公平比较', page: 5,
      quote: 'Holding equal the optimization objective, data access, and future reference access is imperative to properly evaluate differences in controller synthesis approaches.',
      translation: '比较控制器之前，要先对齐优化目标、数据访问和未来参考信息。',
      questions: [
        { label: '怎样公平比较', question: '怎样才算公平比较？', title: '先对齐三项条件。', tags: ['优化目标', '任务数据', '前馈信息'], answer: '条件不一致，差距就可能来自实验设置。' },
        { label: '为什么重要', question: '为什么要先对齐条件？', title: '给方法相同的起跑线。', tags: ['同一目标', '同样数据', '相同参考'], answer: '先消除条件差异，才能更清楚地比较方法本身。' }
      ] },
    { id: 'methods', label: '比较什么', page: 2,
      quote: 'In this section we overview two popular classes of controllers, geometric control (GC) and reinforcement learning (RL), that have widely been used for trajectory tracking in quadrotors. Our empirical evaluations and comparisons in later sections will focus on these two classes of controllers.',
      translation: '论文比较两类四旋翼轨迹跟踪方法：几何控制（GC）与强化学习（RL）。',
      questions: [
        { label: '一句话解释', question: '这篇论文在比较什么？', title: '两类方法，同一个任务。', tags: ['几何控制 GC', '强化学习 RL', '轨迹跟踪'], answer: '让 GC 与 RL 都完成四旋翼轨迹跟踪，再比较它们的表现。' },
        { label: '接着读哪里', question: '认识方法后，下一步看什么？', title: '先看比赛条件。', tags: ['优化目标', '任务数据', '前馈信息'], answer: '接着看第 5 页：目标、数据与未来参考信息，是否对两类方法同样开放。' }
      ] },
    { id: 'tradeoff', label: '读懂结论', page: 1,
      quote: 'Geometric control achieves lower steady-state error than RL, while RL has better transient performance, resulting in GC performing better in relatively slow or less agile tasks, but RL performing better when greater agility is required.',
      translation: 'GC 的稳态误差更低，RL 的瞬态表现更好：较慢任务偏向 GC，更敏捷的任务偏向 RL。',
      questions: [
        { label: '一句话解释', question: '稳态与瞬态，有什么区别？', title: '稳定以后，还是变化之初？', tags: ['GC：稳态误差', 'RL：瞬态响应', '结合任务判断'], answer: '稳态看稳定后的误差，瞬态看状态变化时的响应；论文中的两类方法各有优势。' },
        { label: '谁更好', question: '能直接说某一种方法更好吗？', title: '先看任务需要什么。', tags: ['任务速度', '敏捷要求', '评价指标'], answer: '这项研究没有给出统一赢家：较慢任务与高敏捷任务，对控制器的要求不同。' }
      ] }
  ];
  const $ = selector => document.querySelector(selector);
  const colors = { yellow: ['#f3da92', '黄色'], green: ['#b4dfb1', '绿色'], blue: ['#b9d5f5', '蓝色'], pink: ['#f2bed0', '粉色'], purple: ['#d5c2f0', '紫色'] };
  const freshState = sample => ({ translation: sample.translation, draft: sample.translation, editing: false, marks: [], question: null, reference: null });
  const states = new Map(samples.map(sample => [sample.id, freshState(sample)]));
  const notes = new Map(), animations = new Set();
  const popover = $('#selection-popover'), annotationDialog = $('#annotation-dialog');
  const original = $('#sample-quote'), translated = $('#sample-translation');
  let currentId = 'fairness', view = 'parallel', lastColor = 'yellow';
  let activeSelection = null, pendingAnnotation = null, dragging = false, selectionFrame = 0, nextMarkId = 1;
  let matches = [], matchIndex = -1;
  const current = () => samples.find(sample => sample.id === currentId);
  const state = () => states.get(currentId);
  const textFor = (id, scope) => scope === 'original' ? samples.find(sample => sample.id === id).quote : states.get(id).translation;
  const motionAllowed = () => document.documentElement.dataset.motion === 'on';
  const say = text => { $('#sample-status').textContent = text; };
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  function button(text, action, className = 'sample-text-button') {
    const element = node('button', text, className);
    element.type = 'button'; element.addEventListener('click', action); return element;
  }
  function animate(element) {
    if (!motionAllowed()) return;
    const animation = element.animate([{ opacity: .45, translate: '0 8px' }, { opacity: 1, translate: '0 0' }], { duration: 280, easing: 'ease-out' });
    animations.add(animation);
    animation.finished.then(() => animations.delete(animation), () => animations.delete(animation));
  }
  document.addEventListener('parallel-motion-change', event => {
    if (!event.detail.enabled) { for (const animation of animations) animation.cancel(); animations.clear(); }
  });
  function hidePopover() { popover.hidden = true; }
  function dismissPopover() { cancelAnimationFrame(selectionFrame); selectionFrame = 0; hidePopover(); }
  function showTool(name) {
    document.querySelectorAll('[data-tool]').forEach(tab => {
      const selected = tab.dataset.tool === name;
      tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
      $(`#panel-${tab.dataset.tool}`).hidden = !selected;
    });
  }
  const toolTabs = [...document.querySelectorAll('[data-tool]')];
  toolTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => showTool(tab.dataset.tool));
    tab.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % 3 : event.key === 'ArrowLeft' ? (index + 2) % 3 : event.key === 'Home' ? 0 : event.key === 'End' ? 2 : null;
      if (next === null) return;
      event.preventDefault(); showTool(toolTabs[next].dataset.tool); toolTabs[next].focus();
    });
  });
  function setView(next) {
    view = next; hidePopover();
    $('#original-pane').hidden = view === 'translation'; $('#translation-pane').hidden = view === 'original';
    document.querySelectorAll('[data-reading-view]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.readingView === view)));
  }
  document.querySelectorAll('[data-reading-view]').forEach(item => item.addEventListener('click', () => setView(item.dataset.readingView)));
  function renderText(element, scope) {
    const text = textFor(currentId, scope);
    const marks = state().marks.filter(mark => mark.scope === scope && text.slice(mark.start, mark.end) === mark.text);
    const found = matches.filter(match => match.id === currentId && match.scope === scope);
    const boundaries = new Set([0, text.length]);
    [...marks, ...found].forEach(item => { boundaries.add(item.start); boundaries.add(item.end); });
    const positions = [...boundaries].sort((a, b) => a - b), fragment = document.createDocumentFragment();
    for (let index = 0; index < positions.length - 1; index++) {
      const start = positions[index], end = positions[index + 1];
      const mark = marks.findLast(item => start >= item.start && end <= item.end);
      const match = found.find(item => start >= item.start && end <= item.end);
      if (!mark && !match) { fragment.append(document.createTextNode(text.slice(start, end))); continue; }
      const span = node(mark ? 'mark' : 'span', text.slice(start, end));
      if (mark) { span.dataset.markId = mark.id; span.style.setProperty('--sample-highlight', colors[mark.color][0]); span.className = 'reader-mark'; }
      if (match) { span.classList.add('search-hit'); if (matches[matchIndex] === match) span.classList.add('current-hit'); }
      fragment.append(span);
    }
    element.replaceChildren(fragment);
  }
  function renderReader() {
    renderText(original, 'original'); renderText(translated, 'translation');
    $('#sample-page').textContent = `第 ${current().page} 页`;
    $('#translation-editor').hidden = !state().editing; translated.hidden = state().editing;
    $('#translation-input').value = state().draft;
    $('#edit-translation').setAttribute('aria-expanded', String(state().editing));
  }
  function renderAnswer() {
    const entry = state();
    $('#sample-reference').hidden = !entry.reference; $('#reference-text').textContent = entry.reference?.text || '';
    $('#sample-empty').hidden = entry.question !== null; $('#sample-answer').hidden = entry.question === null;
    $('#sample-questions').replaceChildren(...current().questions.map((question, index) => {
      const item = button(question.label, () => ask(index), 'question-chip');
      item.dataset.question = String(index); item.setAttribute('aria-pressed', String(entry.question === index)); return item;
    }));
    if (entry.question === null) return;
    const question = current().questions[entry.question];
    $('#sample-question').textContent = question.question; $('#sample-answer-title').textContent = question.title; $('#sample-answer-copy').textContent = question.answer;
    $('#answer-conditions').replaceChildren(...question.tags.map((tag, index) => { const span = node('span'); span.append(node('b', `0${index + 1}`), document.createTextNode(tag)); return span; }));
    $('#sample-citation').textContent = `↗ 查原文 · 第 ${current().page} 页`;
    $('#save-sample').textContent = notes.has(`${currentId}:${entry.question}`) ? '★ 已收藏 · 查看笔记' : '☆ 收藏这条理解';
  }
  function selectSample(id) {
    hidePopover(); activeSelection = null; currentId = id;
    $('#sample-source').classList.remove('is-located');
    document.querySelectorAll('[data-sample]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.sample === id)));
    renderReader(); renderAnswer();
  }
  document.querySelectorAll('[data-sample]').forEach(item => item.addEventListener('click', () => selectSample(item.dataset.sample)));
  function ask(index) {
    state().question = index; showTool('ask'); renderAnswer(); animate($('#sample-answer'));
    say('已展示这段的预置教学解释，可以查出处或收藏。');
  }
  $('#explain-sample').addEventListener('click', () => ask(0));
  $('#clear-reference').addEventListener('click', () => { state().reference = null; renderAnswer(); });
  function locate(id, scope = 'original', markId = null) {
    selectSample(id);
    if ((scope === 'original' && view === 'translation') || (scope === 'translation' && view === 'original')) setView('parallel');
    if (scope === 'translation' && state().editing) { state().editing = false; renderReader(); }
    const element = scope === 'original' ? original : translated;
    const mark = state().marks.find(item => item.id === markId);
    if (mark && textFor(id, scope).slice(mark.start, mark.end) !== mark.text) { say('译文已修改，原选区仍保留在批注中。'); return; }
    $('#sample-source').classList.add('is-located'); element.focus({ preventScroll: true });
    element.scrollIntoView({ behavior: motionAllowed() ? 'smooth' : 'instant', block: 'center' });
    say(`已回到第 ${current().page} 页${scope === 'original' ? '原文' : '译文'}${mark ? '的标记' : ''}。`);
  }
  $('#sample-citation').addEventListener('click', () => locate(currentId));
  function findMatches() {
    const term = $('#sample-search').value.trim().toLocaleLowerCase(); matches = []; matchIndex = -1;
    if (term) for (const sample of samples) for (const scope of ['original', 'translation']) {
      const text = textFor(sample.id, scope).toLocaleLowerCase(); let start = 0;
      while ((start = text.indexOf(term, start)) !== -1) { matches.push({ id: sample.id, scope, start, end: start + term.length }); start += term.length; }
    }
    $('#previous-match').disabled = $('#next-match').disabled = !matches.length;
    $('#search-count').textContent = term ? `${matches.length} 处` : ''; renderReader();
    if (matches.length) goToMatch(0);
  }
  function goToMatch(index) {
    if (!matches.length) return;
    matchIndex = (index + matches.length) % matches.length; const match = matches[matchIndex]; selectSample(match.id);
    if (view !== 'parallel') setView(match.scope === 'original' ? 'original' : 'translation');
    if (match.scope === 'translation' && state().editing) { state().editing = false; renderReader(); }
    $('#search-count').textContent = `${matchIndex + 1} / ${matches.length}`;
  }
  $('#sample-search').addEventListener('input', findMatches);
  $('#sample-search-form').addEventListener('submit', event => { event.preventDefault(); goToMatch(matchIndex + 1); });
  $('#previous-match').addEventListener('click', () => goToMatch(matchIndex - 1));
  $('#edit-translation').addEventListener('click', () => { hidePopover(); state().editing = true; renderReader(); $('#translation-input').focus(); });
  $('#translation-input').addEventListener('input', event => { state().draft = event.target.value; });
  function saveTranslation(text) {
    const entry = state(); entry.translation = entry.draft = text; entry.editing = false;
    // Keep annotations after edits; re-anchor only when their text remains unambiguous.
    entry.marks.filter(mark => mark.scope === 'translation').forEach(mark => {
      const start = text.indexOf(mark.text);
      if (start !== -1 && text.indexOf(mark.text, start + 1) === -1) { mark.start = start; mark.end = start + mark.text.length; }
    });
    const selectedId = currentId; findMatches(); selectSample(selectedId); renderShelves();
    $('#edit-translation').focus(); say('译文已更新；你的批注仍保留在右侧。');
  }
  $('#translation-editor').addEventListener('submit', event => { event.preventDefault(); const text = state().draft.trim(); if (text) saveTranslation(text); });
  $('#cancel-translation').addEventListener('click', () => { state().editing = false; state().draft = state().translation; renderReader(); $('#edit-translation').focus(); });
  $('#restore-translation').addEventListener('click', () => saveTranslation(current().translation));
  function selectionContainer(target) { return (target?.nodeType === Node.ELEMENT_NODE ? target : target?.parentElement)?.closest('[data-selectable]'); }
  function positionPopover(rect) {
    popover.hidden = false; const box = popover.getBoundingClientRect();
    const left = Math.max(10, Math.min(innerWidth - box.width - 10, rect.left + rect.width / 2 - box.width / 2));
    const above = rect.top - box.height - 10;
    const top = above >= 10 ? above : Math.min(innerHeight - box.height - 10, rect.bottom + 10);
    popover.style.left = `${left}px`; popover.style.top = `${Math.max(10, Math.min(innerHeight - box.height - 10, top))}px`;
  }
  function updatePopover(rect) {
    const existing = state().marks.find(mark => mark.id === activeSelection?.markId);
    document.querySelectorAll('button[data-highlight]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.highlight === (existing?.color || lastColor))));
    $('#remove-selection-mark').hidden = !existing; positionPopover(rect);
  }
  function captureSelection() {
    if (annotationDialog.open || dragging) return;
    const selection = getSelection();
    if (!selection?.rangeCount || selection.isCollapsed) {
      if (activeSelection?.origin !== 'mark') { hidePopover(); activeSelection = null; }
      return;
    }
    const range = selection.getRangeAt(0), container = selectionContainer(range.startContainer);
    if (!container || container !== selectionContainer(range.endContainer) || !container.checkVisibility()) { hidePopover(); return; }
    const rect = range.getBoundingClientRect();
    if (rect.bottom <= 0 || rect.top >= innerHeight || rect.right <= 0 || rect.left >= innerWidth) { hidePopover(); return; }
    const prefix = range.cloneRange(); prefix.selectNodeContents(container); prefix.setEnd(range.startContainer, range.startOffset);
    const raw = range.toString(), trimmed = raw.trim(); if (!trimmed) { hidePopover(); return; }
    const start = prefix.toString().length + raw.indexOf(trimmed), end = start + trimmed.length, scope = container.dataset.selectable;
    const existing = state().marks.find(mark => mark.scope === scope && mark.start === start && mark.end === end && mark.text === trimmed);
    activeSelection = { sampleId: currentId, scope, start, end, text: trimmed, markId: existing?.id, origin: 'native' }; updatePopover(rect);
  }
  function queueSelectionCapture() { cancelAnimationFrame(selectionFrame); selectionFrame = requestAnimationFrame(captureSelection); }
  document.addEventListener('selectionchange', queueSelectionCapture);
  document.addEventListener('pointerdown', event => {
    if (popover.contains(event.target)) { event.preventDefault(); return; }
    hidePopover(); activeSelection = null;
    const selectable = event.target.closest('[data-selectable]');
    dragging = Boolean(selectable);
    if (selectable) selectable.focus({ preventScroll: true });
  });
  document.addEventListener('pointerup', () => { const wasSelecting = dragging; dragging = false; if (wasSelecting) queueSelectionCapture(); });
  document.addEventListener('pointercancel', () => { dragging = false; hidePopover(); });
  window.addEventListener('scroll', dismissPopover, { passive: true, capture: true });
  window.addEventListener('resize', dismissPopover, { passive: true });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { hidePopover(); getSelection()?.removeAllRanges(); } });
  [original, translated].forEach(element => {
    element.addEventListener('keydown', event => {
      if (event.key === 'Tab' && !event.shiftKey && !popover.hidden) { event.preventDefault(); $('#selection-annotate').focus(); return; }
      if (!event.shiftKey && event.key.startsWith('Arrow')) hidePopover();
      if (!event.shiftKey || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
      const selection = getSelection();
      if (!selection.rangeCount || selectionContainer(selection.anchorNode) !== element) {
        const range = document.createRange(); range.selectNodeContents(element); range.collapse(true); selection.removeAllRanges(); selection.addRange(range);
      }
      if (typeof selection.modify === 'function') {
        event.preventDefault();
        const granularity = ['ArrowUp', 'ArrowDown'].includes(event.key) ? 'line' : event.ctrlKey || event.altKey ? 'word' : event.metaKey ? 'lineboundary' : 'character';
        selection.modify('extend', ['ArrowLeft', 'ArrowUp'].includes(event.key) ? 'backward' : 'forward', granularity); captureSelection();
      }
    });
    element.addEventListener('click', event => {
      if (!getSelection()?.isCollapsed) return;
      const target = event.target.closest('[data-mark-id]'); if (!target) return;
      const mark = state().marks.find(item => item.id === target.dataset.markId);
      activeSelection = { ...mark, sampleId: currentId, markId: mark.id, origin: 'mark' }; updatePopover(target.getBoundingClientRect());
    });
  });
  $('#select-example').addEventListener('click', () => {
    const element = view === 'translation' ? translated : original;
    if (element === translated && state().editing) { state().editing = false; renderReader(); }
    element.focus({ preventScroll: true }); element.scrollIntoView({ block: 'center', behavior: 'instant' });
    const range = document.createRange(); range.selectNodeContents(element);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); captureSelection();
  });
  function upsertMark(selection, color, note) {
    const entry = states.get(selection.sampleId); let mark = entry.marks.find(item => item.id === selection.markId);
    if (!mark) { mark = { id: `mark-${nextMarkId++}`, scope: selection.scope, start: selection.start, end: selection.end, text: selection.text, color, note: '' }; entry.marks.push(mark); }
    mark.color = color; if (note !== undefined) mark.note = note; return mark;
  }
  function applyHighlight(color) {
    if (!activeSelection) return;
    upsertMark(activeSelection, color); lastColor = color;
    hidePopover(); getSelection()?.removeAllRanges(); renderReader(); renderShelves();
    say(`已将实际选中的文字标为${colors[color][1]}。点击标记可改色或添加批注。`);
  }
  document.querySelectorAll('button[data-highlight]').forEach(item => item.addEventListener('click', () => applyHighlight(item.dataset.highlight)));
  $('#selection-highlight').addEventListener('click', () => applyHighlight(lastColor));
  function editAnnotation(selection) {
    pendingAnnotation = { ...selection }; const mark = states.get(selection.sampleId).marks.find(item => item.id === selection.markId);
    $('#annotation-selection').textContent = selection.text; $('#sample-annotation-input').value = mark?.note || '';
    hidePopover(); annotationDialog.showModal(); $('#sample-annotation-input').focus();
  }
  $('#selection-annotate').addEventListener('click', () => { if (activeSelection) editAnnotation(activeSelection); });
  $('#close-annotation').addEventListener('click', () => annotationDialog.close());
  $('#cancel-annotation').addEventListener('click', () => annotationDialog.close());
  annotationDialog.addEventListener('close', () => { pendingAnnotation = null; getSelection()?.removeAllRanges(); });
  $('#annotation-form').addEventListener('submit', event => {
    event.preventDefault(); const text = $('#sample-annotation-input').value.trim(); if (!text || !pendingAnnotation) return;
    const old = states.get(pendingAnnotation.sampleId).marks.find(item => item.id === pendingAnnotation.markId);
    upsertMark(pendingAnnotation, old?.color || lastColor, text);
    annotationDialog.close(); renderReader(); renderShelves(); showTool('marks'); say('批注已绑定到刚才选中的文字，可在列表中回看。');
  });
  $('#selection-explain').addEventListener('click', () => { if (activeSelection) { state().reference = { ...activeSelection }; hidePopover(); ask(0); } });
  $('#selection-cite').addEventListener('click', () => {
    if (!activeSelection) return;
    state().reference = { ...activeSelection }; state().question = null;
    hidePopover(); showTool('ask'); renderAnswer(); say('已带入选中文字，选一个问题接着读。');
  });
  function removeMark(id, markId) {
    const entry = states.get(id); entry.marks = entry.marks.filter(mark => mark.id !== markId);
    hidePopover(); renderReader(); renderShelves(); say('已删除这条标记与批注。');
  }
  $('#remove-selection-mark').addEventListener('click', () => { if (activeSelection?.markId) removeMark(currentId, activeSelection.markId); });
  function renderShelves() {
    const markItems = samples.flatMap(sample => states.get(sample.id).marks.map(mark => ({ sample, mark })));
    $('#mark-count').textContent = String(markItems.length); $('#note-count').textContent = String(notes.size);
    $('#marks-empty').hidden = Boolean(markItems.length); $('#notes-empty').hidden = Boolean(notes.size);
    $('#export-sample').disabled = !(notes.size || markItems.length || samples.some(sample => states.get(sample.id).translation !== sample.translation));
    $('#sample-mark-list').replaceChildren(...markItems.map(({ sample, mark }) => {
      const item = node('article', undefined, 'shelf-card'); item.dataset.savedMark = mark.id; item.style.setProperty('--mark-color', colors[mark.color][0]);
      const target = button(`${sample.label} · 第 ${sample.page} 页 · ${mark.scope === 'original' ? '原文' : '译文'} ↗`, () => locate(sample.id, mark.scope, mark.id), 'shelf-location');
      const actions = node('div', undefined, 'shelf-actions');
      actions.append(button(mark.note ? '编辑批注' : '写批注', () => editAnnotation({ ...mark, sampleId: sample.id, markId: mark.id })), button('删除', () => removeMark(sample.id, mark.id)));
      item.append(target, node('blockquote', mark.text), ...(mark.note ? [node('p', mark.note)] : []), actions); return item;
    }));
    $('#sample-note-list').replaceChildren(...[...notes.values()].map(note => {
      const item = node('article', undefined, 'shelf-card'); item.dataset.savedNote = note.key; item.append(node('strong', note.title), node('p', note.answer));
      const actions = node('div', undefined, 'shelf-actions');
      actions.append(button(`第 ${note.page} 页 ↗`, () => locate(note.sampleId)), button('移除', () => { notes.delete(note.key); renderShelves(); renderAnswer(); say('已移除这条笔记。'); }));
      item.append(actions); return item;
    }));
  }
  $('#save-sample').addEventListener('click', () => {
    if (state().question === null) return;
    const key = `${currentId}:${state().question}`; if (notes.has(key)) { showTool('notes'); return; }
    notes.set(key, { ...current().questions[state().question], key, sampleId: currentId, page: current().page, quote: current().quote, selected: state().reference?.text || '' });
    renderShelves(); renderAnswer(); say(`已收藏。笔记里已有 ${notes.size} 条理解。`);
  });
  $('#export-sample').addEventListener('click', () => {
    const lines = ['# 页间 · 我的阅读体验', '', '> 预置教学内容；批注由本次体验填写。', ''];
    for (const note of notes.values()) lines.push(`## ${note.title}`, '', note.question, '', note.answer, '', `第 ${note.page} 页原文：`, '', `> ${note.quote}`, '', ...(note.selected ? ['引用选段：', '', `> ${note.selected}`, ''] : []));
    for (const sample of samples) for (const mark of states.get(sample.id).marks) lines.push('## 高亮与批注', '', `${sample.label} · 第 ${sample.page} 页 · ${mark.scope === 'original' ? '原文' : '译文'} · ${colors[mark.color][1]}`, '', `> ${mark.text}`, '', ...(mark.note ? [mark.note, ''] : []));
    for (const sample of samples) if (states.get(sample.id).translation !== sample.translation) lines.push(`## 我的译文 · ${sample.label}`, '', states.get(sample.id).translation, '');
    lines.push('## 素材出处', '', 'Leveling the Playing Field: Carefully Comparing Classical and Learned Controllers for Quadrotor Trajectory Tracking（2025）。', '', 'Pratik Kunapuli、Jake Welde、Dinesh Jayaraman、Vijay Kumar。', '', 'https://arxiv.org/abs/2506.17832v1', '', 'CC BY 4.0：https://creativecommons.org/licenses/by/4.0/ 。中文为教学改编，非现场模型回答；作者不为软件背书。', '');
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = '页间-我的阅读体验.md'; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000); say('笔记、批注与修改的译文已导出。');
  });
  $('#reset-sample').addEventListener('click', () => {
    for (const animation of animations) animation.cancel(); animations.clear();
    hidePopover(); activeSelection = null; getSelection()?.removeAllRanges(); notes.clear(); matches = []; matchIndex = -1;
    for (const sample of samples) states.set(sample.id, freshState(sample));
    $('#sample-search').value = ''; $('#search-count').textContent = ''; $('#previous-match').disabled = $('#next-match').disabled = true;
    setView('parallel'); selectSample('fairness'); renderShelves(); showTool('ask'); say('本次体验已重置。');
  });
  renderReader(); renderAnswer(); renderShelves();
})();
