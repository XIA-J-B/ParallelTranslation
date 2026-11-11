'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function highlights({quotes,revision='current-pdf',sourceVersion='new-source',sourceLegacy='old-source',translationVersion='new-translation',translationLegacy='old-translation'}){
  const drawn=[];
  const sourceLayer={dataset:{version:sourceVersion,legacyVersion:sourceLegacy}};
  const translatedLayer={dataset:{version:translationVersion,legacyVersion:translationLegacy}};
  function pane(layer){
    const page={querySelector:selector=>selector==='.pdf-text-layer'?layer:null,
      append:element=>drawn.push({pane:result,element})};
    const result={addEventListener(){},contains:()=>false,
      querySelector:selector=>selector==='[data-page-index="0"]'?page:null};
    return result;
  }
  const source=pane(sourceLayer),translation=pane(translatedLayer);
  const classes=()=>({add(){},remove(){}});
  const button={classList:classes(),setAttribute(){}};
  const float={classList:classes(),setAttribute(){},addEventListener(){},
    querySelector:()=>button,querySelectorAll:()=>[]};
  const document={querySelector:selector=>selector==='#source-pane'?source:translation,
    querySelectorAll:selector=>selector==='.saved-text-highlight'?drawn.map(x=>x.element):[],
    createElement:tag=>tag==='div' && !document.createdFloat?(document.createdFloat=true,float):
      {dataset:{},style:{},remove(){this.removed=true;}},
    addEventListener(){},body:{append(){}}};
  let pending;
  const context=vm.createContext({window:{},document,state:{doc:{id:'doc'},layout:{revision}},
    stored:(key,fallback)=>key==='parallel-highlights-doc'?quotes:fallback,
    persist:()=>true,MutationObserver:class{observe(){}},ResizeObserver:class{observe(){}},
    setTimeout:callback=>(pending=callback),clearTimeout(){},structuredClone});
  vm.runInContext(fs.readFileSync(require.resolve('../static/reading-selection.js'),'utf8'),context);
  pending();
  return {drawn:drawn.filter(x=>!x.element.removed),context,source,translation};
}

function quote({version='old-source',view='source',revision=null,doc='doc',page=1}={}){
  return {id:'saved',source:{doc_id:doc,view,revision,page,text_version:version,
    rects:[[.1,.2,.4,.25]],ranges:[{run_id:'r7',start:3,end:8}]},
    request:{page,view,revision,text_version:version,ranges:[{run_id:'r7',start:3,end:8}]}};
}

test('same-PDF legacy highlights retain their rectangles and original request offsets',()=>{
  for(const version of ['new-source','old-source']){
    const saved=quote({version});
    const before=structuredClone(saved);
    const result=highlights({quotes:[saved]});
    assert.equal(result.drawn.length,1);
    assert.equal(result.drawn[0].pane,result.source);
    assert.equal(result.drawn[0].element.style.left,'10%');
    assert.ok(Math.abs(parseFloat(result.drawn[0].element.style.width)-30)<1e-10);
    assert.deepEqual(saved,before);
    assert.deepEqual(JSON.parse(JSON.stringify(result.context.OriginalTextSelection.highlights()[0].request)),saved.request);
  }
});

test('unmatched or absent version never paints a legacy highlight',()=>{
  assert.equal(highlights({quotes:[quote({version:'other-pdf'})]}).drawn.length,0);
  const missing=quote();delete missing.source.text_version;
  assert.equal(highlights({quotes:[missing]}).drawn.length,0);
  assert.equal(highlights({quotes:[quote({version:''})],sourceVersion:undefined,sourceLegacy:undefined}).drawn.length,0);
});

test('translation legacy highlights still require their exact PDF revision and document/page ownership',()=>{
  const saved=quote({version:'old-translation',view:'translation',revision:'current-pdf'});
  const result=highlights({quotes:[saved]});
  assert.equal(result.drawn.length,1);assert.equal(result.drawn[0].pane,result.translation);
  for(const overrides of [{revision:'another-pdf'},{doc:'another-document'},{page:2}]){
    assert.equal(highlights({quotes:[quote({version:'old-translation',view:'translation',revision:'current-pdf',...overrides})]}).drawn.length,0);
  }
  assert.equal(highlights({quotes:[quote({version:'old-source',view:'translation',revision:'current-pdf'})]}).drawn.length,0);
});
