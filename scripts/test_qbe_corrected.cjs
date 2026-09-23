const fs=require('fs'),vm=require('vm'),assert=require('assert');
const data=JSON.parse(fs.readFileSync('leaderboard/quantumbencheval.json'));
const elements={};global.document={getElementById:id=>elements[id] ||= {innerHTML:'',querySelectorAll:()=>[]}};global.window={};global.fetch=async()=>({ok:true,json:async()=>data});
vm.runInThisContext(fs.readFileSync('leaderboard/quantumbencheval.js','utf8'));
(async()=>{
 const state={collection:'qbe',topic:'T1',view:'leaderboard'};
 await window.renderQBE(state,()=>{});
 assert(elements['board-body'].innerHTML.includes('83.53%'));
 assert(elements['board-body'].innerHTML.includes('94.12%'));
 assert(!elements['qbe-notes'].innerHTML.includes('Preview'));
 assert(!elements['qbe-notes'].innerHTML.includes('Sample statuses'));
 for(const r of data.topics[0].rows) {
  Object.assign(state,{view:'problems',selected:r.task_id,attempt:r.sample_index});
  await window.renderQBE(state,()=>{});
  const html=elements['problem-detail'].innerHTML;
  assert(r.generation.code.length>0);
  assert(!html.includes('No output available.'));
  const correct=r.corrected_evaluation.graded_status==='passed';
  assert(html.includes(`class="attempt-output ${correct?'correct':'incorrect'}"`));
  if (r.corrected_evaluation.metrics) assert(html.includes('metrics'));
 }
 const sample=data.topics[0].rows.find(r=>r.task_id==='t1_0'&&r.sample_index===0);
 assert.equal(sample.status,'incorrect');assert.equal(sample.corrected_evaluation.graded_status,'passed');
 assert.equal(sample.corrected_evaluation.metrics.shots_closeness,.25);
 assert.equal(sample.corrected_evaluation.metrics.optimizer_calls_closeness,.4625);
 console.log('Corrected leaderboard and all 85 joined attempt outputs passed.');
})();
