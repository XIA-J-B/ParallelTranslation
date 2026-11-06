'use strict';
if(typeof window!=='undefined'){
  const cache=new Map(),pending=new Set();let documentId=null,sequence=0,space=false,selectionRequests=[],highlights=[],activeHighlights=[],paintedHighlights=[];
  const colors={yellow:{label:'黄色',value:'#f2cf4c'},green:{label:'绿色',value:'#70cf96'},blue:{label:'蓝色',value:'#7fb5f5'},pink:{label:'粉色',value:'#f397b8'},purple:{label:'紫色',value:'#b39aef'}};
  let selectedColor=stored('parallel-highlight-color','yellow');if(!Object.hasOwn(colors,selectedColor))selectedColor='yellow';
  const panes=[document.querySelector('#source-pane'),document.querySelector('#translation-pane')];
  const float=document.createElement('div');float.id='quote-toolbar';float.className='hidden';
  float.setAttribute('role','toolbar');float.setAttribute('aria-label','选中文字操作');
  float.innerHTML='<div class="quote-actions"><button data-quote="explain">解释</button><button data-quote="add">引用</button><button data-quote="highlight">高亮</button><button data-quote="remove-highlight" class="hidden">取消高亮</button></div>'+
    '<div class="highlight-colors" role="group" aria-label="高亮颜色">'+Object.entries(colors).map(([key,color])=>`<button data-highlight-color="${key}" style="--highlight-color:${color.value}" aria-label="${color.label}高亮" title="${color.label}高亮" aria-pressed="${key===selectedColor}"></button>`).join('')+'</div>';
  document.body.append(float);
  const canvas=document.createElement('canvas'),measure=canvas.getContext('2d');
  function place(page,layer,view,revision){
    const root=document.createElement('div');root.className='original-text-layer';root.dataset.page=layer.page;root.dataset.version=layer.version;root.dataset.view=view;if(revision)root.dataset.revision=revision;
    for(const run of layer.runs){
      const outer=document.createElement('span');outer.className='source-text-position';
      const span=document.createElement('span');span.className='source-text-run';span.dataset.run=run.id;span.textContent=run.text;
      outer.append(span);root.append(outer);
    }
    if(layer.note || layer.warnings.length){const notice=document.createElement('small');notice.className='text-layer-notice';notice.textContent=layer.note || layer.warnings.join(' ');root.append(notice);}
    page.append(root);resize(page,layer);
  }
  function resize(page,layer){
    const width=page.getBoundingClientRect().width,height=page.getBoundingClientRect().height;
    const scale=width/layer.width;
    page.querySelectorAll('.source-text-position').forEach((outer,i)=>{
      const run=layer.runs[i],a=run.corners[0],b=run.corners[1],c=run.corners[2];
      const dx=(b[0]-a[0])*width,dy=(b[1]-a[1])*height;
      const length=Math.hypot(dx,dy),lineHeight=Math.hypot((c[0]-a[0])*width,(c[1]-a[1])*height);
      const font=/Times|Serif|Roman/i.test(run.font)?'"Times New Roman",serif':'Arial,sans-serif';
      const size=run.size*scale;measure.font=`${size}px ${font}`;
      const actual=measure.measureText(run.text).width || 1;
      Object.assign(outer.style,{left:a[0]*100+'%',top:a[1]*100+'%',height:lineHeight+'px',transform:`rotate(${Math.atan2(dy,dx)}rad)`});
      Object.assign(outer.firstChild.style,{fontFamily:font,fontSize:size+'px',lineHeight:lineHeight+'px',transform:`scaleX(${length/actual})`});
    });
  }
  async function refresh(){
    if(!state.doc)return;
    if(documentId!==state.doc.id){documentId=state.doc.id;sequence++;cache.clear();pending.clear();hide();highlights=stored('parallel-highlights-'+documentId,[]);if(!Array.isArray(highlights))highlights=[];}
    const epoch=sequence,id=documentId;
    for(const pane of panes){
      const bounds=pane.getBoundingClientRect();if(!bounds.width || !bounds.height)continue;
      const revision=pane===panes[1]?state.layout?.revision:null,view=revision?'translation':'source';
      for(const page of pane.querySelectorAll('.pdf-page')){
        const rect=page.getBoundingClientRect(),number=state.doc.pages[Number(page.dataset.pageIndex)].number,key=JSON.stringify([id,revision,number]);
        const visible=rect.bottom>bounds.top-bounds.height && rect.top<bounds.bottom+bounds.height;
        if(!visible){if(!getSelection()?.toString())page.querySelector('.original-text-layer')?.remove();continue;}
        if(cache.has(key)){if(!page.querySelector('.original-text-layer'))place(page,cache.get(key),view,revision);else resize(page,cache.get(key));continue;}
        if(pending.has(key))continue;pending.add(key);
        try{const layer=await api(`/api/documents/${id}/reading/text/${number}${revision?'?revision='+revision:''}`);if(epoch!==sequence || state.doc?.id!==id)return;cache.set(key,layer);if(page.isConnected && !page.querySelector('.original-text-layer'))place(page,layer,view,revision);}
        catch(error){if(epoch===sequence){page.dataset.textLayerError='true';page.title='文字层不可用，请稍后重试或框选原图';}}
        finally{if(epoch===sequence)pending.delete(key);}
      }
    }
    paintHighlights();
  }
  function hide(){float.classList.add('hidden');selectionRequests=[];activeHighlights=[];float.querySelector('[data-quote=remove-highlight]').classList.add('hidden');}
  function positionToolbar(rect){
    float.classList.remove('hidden');float.style.left=Math.max(8,Math.min(innerWidth-float.offsetWidth-8,rect.left))+'px';float.style.top=Math.max(8,Math.min(innerHeight-float.offsetHeight-8,rect.top-float.offsetHeight-5))+'px';
  }
  function markColor(color){selectedColor=color;float.querySelectorAll('[data-highlight-color]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.highlightColor===color)));}
  function saveHighlights(next){if(documentId!==state.doc?.id || !persist('parallel-highlights-'+documentId,next))return false;highlights=next;paintHighlights();return true;}
  function highlightAt(event){
    for(const painted of paintedHighlights.slice().reverse()){
      if(painted.pane.contains(event.target) && [...painted.region.getClientRects()].some(rect=>event.clientX>=rect.left && event.clientX<=rect.right && event.clientY>=rect.top && event.clientY<=rect.bottom))return painted;
    }
    return null;
  }
  function positionActiveHighlight(){
    for(const painted of paintedHighlights){
      if(!activeHighlights.includes(painted.quote.id))continue;
      const bounds=painted.pane.getBoundingClientRect();
      for(const rect of painted.region.getClientRects()){
        if(rect.bottom>=bounds.top && rect.top<=bounds.bottom && rect.right>=bounds.left && rect.left<=bounds.right){positionToolbar(rect);return;}
      }
    }
    hide();
  }
  document.addEventListener('pointerdown',event=>{if(!float.contains(event.target))hide();},true);
  let timer;function schedule(){clearTimeout(timer);timer=setTimeout(refresh,120);}
  new MutationObserver(schedule).observe(document.querySelector('#pdf-page'),{childList:true});
  new MutationObserver(schedule).observe(panes[1],{childList:true});
  for(const pane of panes){
    new ResizeObserver(schedule).observe(pane);pane.addEventListener('scroll',()=>{schedule();requestAnimationFrame(()=>{if(activeHighlights.length)positionActiveHighlight();else updateSelection();});},{passive:true});
    pane.addEventListener('pointerdown',e=>{if(e.target.closest('.source-text-run,.translation-text,.source-preview')&&!space&&!document.querySelector('#reader').classList.contains('quote-cropping'))e.stopImmediatePropagation();},true);
    pane.addEventListener('click',e=>{
      if(space || (pane===panes[1]&&state.editTranslation) || document.querySelector('#reader').classList.contains('quote-cropping'))return;
      if(getSelection()?.toString() && e.target.closest('.source-text-run,.translation-text,.source-preview')){e.stopImmediatePropagation();e.preventDefault();return;}
      const painted=highlightAt(e);if(!painted)return;
      e.stopImmediatePropagation();e.preventDefault();hide();activeHighlights=[painted.quote.id];selectionRequests=[structuredClone(painted.quote.request)];
      markColor(Object.hasOwn(colors,painted.quote.color)?painted.quote.color:'yellow');float.querySelector('[data-quote=remove-highlight]').classList.remove('hidden');positionToolbar(painted.region.getBoundingClientRect());
    },true);
  }
  document.addEventListener('keydown',e=>{if(e.code==='Space'&&!e.target.closest('input,textarea,[contenteditable]')){space=true;panes.forEach(p=>p.classList.add('text-pan'));e.preventDefault();}if(e.key==='Escape')hide();});
  function endPan(){space=false;panes.forEach(p=>p.classList.remove('text-pan'));}
  document.addEventListener('keyup',e=>{if(e.code==='Space')endPan();});window.addEventListener('blur',endPan);
  // Map the display's softened whitespace back to the stored paragraph text.
  function characterMap(content,raw){
    const display=Array.from(content.textContent),original=Array.from(raw),map=[];let cursor=0;
    for(const char of display){
      while(cursor<original.length && original[cursor]!==char && /\s/.test(original[cursor]))cursor++;
      if(/\s/.test(char) && !/\s/.test(original[cursor]||'')){map.push(cursor);continue;}
      if(original[cursor]!==char)return null;
      map.push(cursor++);
    }
    return map;
  }
  function paragraphPart(content,range){
    const part=range.cloneRange();if(!content.contains(range.startContainer))part.setStart(content,0);if(!content.contains(range.endContainer))part.setEnd(content,content.childNodes.length);
    const before=document.createRange();before.selectNodeContents(content);before.setEnd(part.startContainer,part.startOffset);
    const block=blocks().find(b=>b.id===content.closest('[data-block]').dataset.block),raw=block.translation || block.text,map=characterMap(content,raw);
    const start=Array.from(before.toString()).length,end=start+Array.from(part.toString()).length;
    if(!map || end<=start)return null;
    return {page:Number(content.closest('.reader-page').dataset.pageIndex)+1,view:'paragraph',block_id:block.id,raw,
      ranges:[{run_id:block.id,start:map[start],end:map[end-1]+1}]};
  }
  function updateSelection(){
    const selection=getSelection();if(activeHighlights.length && (!selection || selection.isCollapsed))return;
    const pane=panes.find(p=>p.contains(selection?.anchorNode)&&p.contains(selection?.focusNode));hide();
    if(!selection?.rangeCount||selection.isCollapsed||!pane||space||(pane===panes[1]&&state.editTranslation))return;
    const range=selection.getRangeAt(0),requests=new Map();
    for(const span of pane.querySelectorAll('.source-text-run')){
      if(!range.intersectsNode(span))continue;
      const text=span.firstChild;if(!text)continue;
      const start=range.startContainer===text?Array.from(text.textContent.slice(0,range.startOffset)).length:0;
      const end=range.endContainer===text?Array.from(text.textContent.slice(0,range.endOffset)).length:Array.from(text.textContent).length;
      if(end<=start)continue;
      const layer=span.closest('.original-text-layer'),page=Number(layer.dataset.page);
      if(!requests.has(page))requests.set(page,{page,text_version:layer.dataset.version,view:layer.dataset.view,revision:layer.dataset.revision || null,ranges:[]});
      requests.get(page).ranges.push({run_id:span.dataset.run,start,end});
    }
    selectionRequests=[...requests.values()];
    for(const content of pane.querySelectorAll('.translation-text,.source-preview')){if(range.intersectsNode(content)){const part=paragraphPart(content,range);if(part)selectionRequests.push(part);}}
    if(!selectionRequests.length)return;
    const rect=range.getBoundingClientRect(),bounds=pane.getBoundingClientRect();if(rect.bottom<bounds.top || rect.top>bounds.bottom)return;
    positionToolbar(rect);
  }
  document.addEventListener('selectionchange',updateSelection);
  float.addEventListener('pointerdown',e=>e.preventDefault());
  float.addEventListener('click',async e=>{
    const color=e.target.closest('[data-highlight-color]')?.dataset.highlightColor;
    if(color){
      if(activeHighlights.length && !saveHighlights(highlights.map(h=>activeHighlights.includes(h.id)?{...h,color}:h)))return;
      markColor(color);persist('parallel-highlight-color',color);return;
    }
    const action=e.target.dataset.quote;if(!action)return;
    if(action==='remove-highlight'){if(saveHighlights(highlights.filter(h=>!activeHighlights.includes(h.id)))){hide();getSelection()?.removeAllRanges();toast('已取消高亮');}return;}
    const id=state.doc?.id,epoch=sequence,highlightColor=selectedColor,requests=selectionRequests.map(r=>structuredClone(r));hide();if(!requests.length)return;
    try{const quotes=[];for(const request of requests){
        if(request.view==='paragraph'){const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(request.raw)));request.text_version=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');delete request.raw;}
        quotes.push(await api(`/api/documents/${id}/reading/citations`,{method:'POST',body:JSON.stringify(request)}));}
      if(epoch!==sequence||state.doc?.id!==id)return;
      if(action==='highlight'){
        const next=[...highlights.filter(h=>!quotes.some(q=>q.id===h.id)),...quotes.map(q=>({...q,color:highlightColor}))];
        if(saveHighlights(next))toast('已高亮，点击高亮文字可调整颜色或取消');
      }else globalThis.PaperAssistant?.addCitations(quotes,action==='explain');getSelection()?.removeAllRanges();
    }catch(error){toast(error.message);}
  });
  function textRange(content,start,end){
    const walker=document.createTreeWalker(content,NodeFilter.SHOW_TEXT),range=document.createRange();let offset=0,node,started=false;
    while(node=walker.nextNode()){
      const length=Array.from(node.textContent).length;
      if(!started && start<offset+length){range.setStart(node,Array.from(node.textContent).slice(0,start-offset).join('').length);started=true;}
      if(started && end<=offset+length){range.setEnd(node,Array.from(node.textContent).slice(0,end-offset).join('').length);return range;}
      offset+=length;
    }
    return null;
  }
  function paragraphRange(source){
    const block=blocks().find(b=>b.id===source.block_id);if(!block)return null;
    const content=document.getElementById('card-'+block.id)?.querySelector('.translation-text,.source-preview');if(!content)return null;
    const raw=block.translation || block.text,map=characterMap(content,raw),item=source.ranges[0];if(!map || !item)return null;
    if(Array.from(raw).slice(item.start,item.end).join('')!==source.text)return null;
    const start=map.findIndex(i=>i>=item.start),last=map.findLastIndex(i=>i<item.end);if(start<0 || last<start)return null;
    return textRange(content,start,last+1);
  }
  function paintHighlights(){
    document.querySelectorAll('.saved-text-highlight').forEach(el=>el.remove());
    paintedHighlights=[];
    const paragraphRanges=Object.fromEntries(Object.keys(colors).map(key=>[key,[]]));
    for(const quote of highlights){
      const source=quote.source;if(!source || source.doc_id!==state.doc?.id)continue;
      const color=Object.hasOwn(colors,quote.color)?quote.color:'yellow';
      if(source.view==='paragraph'){const range=paragraphRange(source);if(range){paragraphRanges[color].push(range);paintedHighlights.push({quote,pane:panes[1],region:range});}continue;}
      for(const pane of panes){
        const revision=pane===panes[1]?state.layout?.revision:null;
        if((source.view==='translation') ? pane!==panes[1] || source.revision!==revision : Boolean(revision))continue;
        const page=pane.querySelector(`[data-page-index="${source.page-1}"]`),layer=page?.querySelector('.original-text-layer');
        if(!layer || layer.dataset.version!==source.text_version)continue;
        for(const [x,y,r,b] of source.rects || []){const el=document.createElement('div');el.className='saved-text-highlight';el.dataset.highlight=quote.id;el.dataset.color=color;Object.assign(el.style,{left:x*100+'%',top:y*100+'%',width:(r-x)*100+'%',height:(b-y)*100+'%',background:colors[color].value+'66'});page.append(el);paintedHighlights.push({quote,pane,region:el});}
      }
    }
    if(globalThis.CSS?.highlights && globalThis.Highlight){for(const [color,ranges] of Object.entries(paragraphRanges))CSS.highlights.set(color==='yellow'?'reader-saved':'reader-saved-'+color,new Highlight(...ranges));}
    if(activeHighlights.length)positionActiveHighlight();
  }
  globalThis.OriginalTextSelection={refresh:schedule,paragraphRange};
  schedule();
}
