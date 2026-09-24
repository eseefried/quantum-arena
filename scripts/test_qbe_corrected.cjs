const fs=require('fs'),vm=require('vm'),assert=require('assert');
const data=JSON.parse(fs.readFileSync('leaderboard/quantumbencheval.json'));
const content=JSON.parse(fs.readFileSync('leaderboard/qbe_content/T1.json'));
const elements={};global.document={getElementById:id=>elements[id] ||= {innerHTML:'',querySelectorAll:()=>[]}};global.window={};
global.fetch=async url=>({ok:true,json:async()=>url.includes('qbe_content/T1.json')?content:data});
vm.runInThisContext(fs.readFileSync('leaderboard/quantumbencheval.js','utf8'));
const settle=()=>new Promise(r=>setTimeout(r,0));
(async()=>{
 const state={collection:'qbe',topic:'T1',view:'leaderboard',qbeModel:'gemini36-flash'};
 await window.renderQBE(state,()=>{});
 assert(elements['board-body'].innerHTML.includes('83.5%'));
 assert(elements['board-body'].innerHTML.includes('94.1%'));
 assert(!elements['qbe-notes'].innerHTML.includes('Preview'));
 assert(!elements['qbe-notes'].innerHTML.includes('Sample statuses'));
 // The score file carries no outputs; they arrive with the per-topic content file.
 assert(!JSON.stringify(data).includes('"code"'));
 const rows=Object.entries(content.models['gemini36-flash']).flatMap(([task_id,attempts])=>attempts.map(r=>({...r,task_id})));
 assert.equal(rows.length,85);
 for(const r of rows) {
  Object.assign(state,{view:'problems',selected:r.task_id,attempt:r.sample_index});
  await window.renderQBE(state,()=>{});await settle();
  const html=elements['problem-detail'].innerHTML;
  assert(r.code.length>0);
  assert(!html.includes('No output available.'));
  const correct=r.corrected_evaluation.graded_status==='passed';
  assert(html.includes(`class="attempt-output ${correct?'correct':'incorrect'}"`));
  if (r.corrected_evaluation.metrics) assert(html.includes('metrics'));
 }
 const sample=rows.find(r=>r.task_id==='t1_0'&&r.sample_index===0);
 assert.equal(sample.status,'incorrect');assert.equal(sample.corrected_evaluation.graded_status,'passed');
 assert.equal(sample.corrected_evaluation.metrics.shots_closeness,.25);
 assert.equal(sample.corrected_evaluation.metrics.optimizer_calls_closeness,.4625);
 console.log('Corrected leaderboard and all 85 joined attempt outputs passed.');
})();
