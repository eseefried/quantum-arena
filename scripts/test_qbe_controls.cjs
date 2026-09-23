// Run with Node: verifies actual Arena control construction and click handlers.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Element {
  constructor() { this.children=[]; this.parentElement={}; this.handlers={}; }
  set innerHTML(value) { this.html=value; this.children=[]; }
  get innerHTML() { return this.html || ''; }
  appendChild(child) { this.children.push(child); }
  addEventListener(name, fn) { this.handlers[name]=fn; }
}
const elements={};
global.document={getElementById:id=>elements[id] ||= new Element(),createElement:()=>new Element()};
global.location={search:''};
let source=fs.readFileSync('leaderboard/leaderboard.js','utf8');
source=source.replace('  init();', '  globalThis.testControls = {state, renderTabs};');
source=source.replace('  function renderCurrentView() {','  function renderCurrentView() { return;');
vm.runInThisContext(source);
const {state,renderTabs}=global.testControls;
const buttons=id=>elements[id].children;
const click=(id,label)=>{const b=buttons(id).find(b=>b.textContent===label);assert(b,`Missing ${label}`);b.handlers.click();};
renderTabs();
assert(elements['collection-control'].hidden);
assert.equal(buttons('collection-tabs').length,0);
click('dataset-tabs','QuantumBenchEval');
assert.equal(state.collection,'qbe');
assert(!elements['collection-control'].hidden);
assert.deepEqual(buttons('collection-tabs').map(b=>b.textContent),['T1','T2','T3','T4','T5','T6']);
click('collection-tabs','T3');assert.equal(state.topic,'T3');
click('view-tabs','Problem View');assert.equal(state.view,'problems');
assert(buttons('dataset-tabs').some(b=>b.textContent==='QuantumBenchEval'));
click('dataset-tabs','QCoder');assert.equal(state.collection,'arena');
assert(elements['collection-control'].hidden);
assert.equal(buttons('collection-tabs').length,0);
const html=fs.readFileSync('leaderboard/index.html','utf8');
assert(html.indexOf('id="collection-control"')>html.indexOf('id="dataset-tabs"'));
console.log('Dataset selection, conditional topics, view switching, and control order passed.');
