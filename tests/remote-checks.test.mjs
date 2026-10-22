import test from 'node:test';
import assert from 'node:assert/strict';
import { checkOne, evaluate, runWatch } from '../scripts/templates/remote-check.mjs';
import { businessSaveResult, persistedResult, trackSave } from '../assets/playwright-runner/support/remote-checks.mjs';
const start=Date.parse('2026-01-01T00:00:00Z');
const check={id:'c', url:'http://example.test/file',method:'GET',timeout_ms:100,
 saved_at:new Date(start).toISOString(),earliest_check_at:new Date(start+3600000).toISOString(),
 deadline:new Date(start+7200000).toISOString(),conditions:[{op:'contains',value:'new'}]};
const response=(body,status=200)=>async()=>new Response(body,{status});
test('save response business codes and persisted values are independently classified',()=>{
 assert.deepEqual(businessSaveResult(true,{code:0}),{businessCode:'code:0',businessOk:true});
 assert.deepEqual(businessSaveResult(true,{status:'FAILED'}),{businessCode:'status:FAILED',businessOk:false});
 assert.equal(businessSaveResult(true,{success:false}).businessOk,false);
 assert.equal(businessSaveResult(true,{code:201},[201]).businessOk,true);
 assert.equal(persistedResult({business_ok:true},'wanted','wanted'),true);
 assert.equal(persistedResult({business_ok:true},'wanted','stale'),false);
 assert.equal(persistedResult({business_ok:false},'wanted','wanted'),false);
});
test('only business-successful tracked saves set savedAt and observations omit bodies',async()=>{
 let listener; const page={on:(_event,fn)=>{listener=fn},off:(_event,fn)=>{assert.equal(listener,fn)}};
 const ctx={caseId:'C'};
 const tracking=trackSave(page,ctx,{method:'POST',path:'/save'});
 listener({url:()=> 'https://example.test/save',request:()=>({method:()=> 'POST'}),ok:()=>true,status:()=>200,json:async()=>({code:409,body:'private'})});
 await Promise.all(ctx.saveTasks);
 assert.equal(ctx.savedAt,undefined); assert.equal(ctx.saves[0].business_ok,false);
 assert.deepEqual(Object.keys(ctx.saves[0]).sort(),['at','business_code','business_ok','http_status','path']);
 listener({url:()=> 'https://example.test/save',request:()=>({method:()=> 'POST'}),ok:()=>true,status:()=>200,json:async()=>({code:0})});
 await Promise.all(ctx.saveTasks); assert.equal(typeof ctx.savedAt,'string'); assert.equal(ctx.saves[1].business_ok,true);
 await tracking.dispose();
});
test('fetch + semantic checks distinguish pass, cached, failure and unreachable',async()=>{
 assert.equal((await checkOne(check,response('new'),()=>start+1000)).status,'pass');
 assert.equal((await checkOne(check,response('old'),()=>start+1000)).status,'still-cached');
 assert.equal((await checkOne(check,response('old'),()=>start+3600001)).status,'fail');
 assert.equal((await checkOne(check,async()=>{throw Error('private detail')},()=>start+1000)).status,'unreachable');
 assert.equal((await checkOne(check,response('new',503),()=>start+3600001)).status,'unreachable');
});
test('cache-bust checks use a unique query variant and return its identity',async()=>{
 let requested;
 const result=await checkOne({...check,cache_bust:true},async url=>{requested=String(url);return new Response('new')},()=>start+1234);
 assert.match(requested,/\?uia_cb=1767225601234-c$/);
 assert.equal(result.variant,'cache_busted');
 assert.equal((await checkOne(check,response('new'),()=>start+1234)).variant,'default');
});
test('late immediate fetch and restored data cannot prove business success',async()=>{
 assert.equal((await checkOne({...check,max_latency_seconds:5},response('new'),()=>start+6000)).reason,'immediate_timing_unverified');
 assert.equal((await checkOne({...check,restored_at:new Date(start+500).toISOString()},response('new'),()=>start+1000)).reason,'data_restored');
});
test('ordered FAQ pairs reject missing extra reversed or single-line data',()=>{
 const condition={op:'ordered_pairs',section:'FAQ',value:[['Q1','A1'],['Q2','A2']]};
 assert.ok(evaluate('## FAQ\nQ1\nA1\nQ2\nA2\n',condition));
 for(const text of ['Q1 A1\nQ2 A2','Q2\nA2\nQ1\nA1','Q1\nA1\nQ2\nA2\nQ3\nA3']) assert.equal(evaluate('## FAQ\n'+text,condition),false);
});
const faq = '## FAQ\n' +
  '- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 5**\nA: UIA answer 5\n' +
  '- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 4**\nA: UIA answer 4\n' +
  '- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 3**\nA: UIA answer 3\n' +
  '- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 2**\nA: UIA answer 2\n' +
  '- **Q: faq标题**\nA: 内容内容\n';
const faqPairs = [5,4,3,2].map(n => [`UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 ${n}`, `UIA answer ${n}`]).concat([['faq标题','内容内容']]);
test('exact markdown FAQ fixture parses in order; reordered and missing pairs fail',()=>{
 const condition={op:'ordered_pairs',section:'FAQ',value:faqPairs};
 assert.equal(evaluate(faq,condition),true);
 const reordered=faq.replace('5**\nA: UIA answer 5','TEMP**\nA: TEMP').replace('4**\nA: UIA answer 4','5**\nA: UIA answer 5').replace('TEMP**\nA: TEMP','4**\nA: UIA answer 4');
 assert.equal(evaluate(reordered,condition),false);
 assert.equal(evaluate(faq.replace('- **Q: UIA FAQ uia-0b66f30241cd450fa08f93aafdb8746d-TC-0033 3**\nA: UIA answer 3\n',''),condition),false);
 assert.equal(evaluate('## FAQ\nQ1\nA1\nQ2\nA2\n',{op:'ordered_pairs',section:'faq',value:[['Q1','A1'],['Q2','A2']]}),true);
 assert.equal(evaluate('### FAQ\n1. **问：你好**\n答：世界\nQ: one A: two\n### Other\nignored\n',{op:'ordered_pairs',section:' faq ',value:[['你好','世界'],['one','two']]}),true);
});
test('checker evidence is bounded and redacts contact and credential patterns',async()=>{
 const jwt=['eyJabcdefghijk','abcdefghijk','abcdefghijk'].join('.');
 const body='safe target person@example.com '+jwt+' 13812345678';
 const result=await checkOne({...check,conditions:[{op:'contains',value:'safe target'}]},response(body),()=>start+1000);
 assert.equal(result.evidence.length,1); assert.ok(result.evidence[0].excerpt.length<=2000);
 assert.doesNotMatch(result.evidence[0].excerpt,/person@example\.com|eyJabcdefghijk|13812345678/);
});
test('watch polls until three present confirmations, records state changes and median clock offset',async()=>{
 let now=start, n=0; const bodies=['old','old','new','new','new'];
 const request={schema_version:'uia-remote-watch.v1',run_id:'R',watch_id:'W',request_sha256:'a'.repeat(64),url:'http://example.test/file',
   method:'GET',conditions:[{op:'contains',value:'new'}],watch_until:new Date(start+20000).toISOString(),interval_ms:1000,timeout_ms:100};
 const result=await runWatch(request,async url=>{
   assert.match(String(url),/uia_cb=/); const body=bodies[n++];
   return new Response(body,{status:200,headers:{Date:new Date(start+5000).toUTCString()}});
 },()=>now,async ms=>{now+=ms;});
 assert.equal(result.poll_count,5); assert.equal(result.confirmed_present,true); assert.equal(result.baseline_absent,true);
 assert.deepEqual(result.timeline.map(x=>x.state),['absent','present']); assert.equal(result.clock_offset_ms,3500); // Date second-resolution +500 ms centring
 assert.ok(result.evidence.section_sha256); assert.equal(result.error_count,0);
});
test('watch records a polling gap without exposing response data',async()=>{
 let now=start;
 const request={schema_version:'uia-remote-watch.v1',run_id:'R',watch_id:'G',request_sha256:'b'.repeat(64),url:'http://example.test/file',
   method:'GET',conditions:[{op:'contains',value:'new'}],watch_until:new Date(start+8000).toISOString(),interval_ms:1000,timeout_ms:100};
 const result=await runWatch(request,async()=>new Response('old'),()=>now,async()=>{now+=6000;});
 assert.equal(result.poll_count,2); assert.equal(result.max_gap_ms,6000); assert.deepEqual(result.polls.map(p=>Object.keys(p)),[['t_ms','ok','present'],['t_ms','ok','present']]);
});
test('watch body stream is hard-bounded by timeout',async()=>{
 const never=()=>new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('old'));}}));
 const t=Date.now(); const result=await checkOne({...check,timeout_ms:50},never,()=>start+1000);
 assert.equal(result.status,'unreachable'); assert.ok(Date.now()-t<500);
});
test('watch dispatches later polls while a prior request hangs',async()=>{
 const request={schema_version:'uia-remote-watch.v1',run_id:'R',watch_id:'H',request_sha256:'c'.repeat(64),url:'http://example.test/file',
   conditions:[{op:'contains',value:'new'}],watch_until:new Date(Date.now()+125).toISOString(),interval_ms:25,timeout_ms:200};
 let calls=0;
 const result=await runWatch(request,()=>{calls++;return new Promise(()=>{});});
 assert.ok(calls>=4); assert.ok(result.error_count>=4);
});
test('watch output uses request-start offsets and sorts completed polls',async()=>{
 const now=Date.now(); const request={schema_version:'uia-remote-watch.v1',run_id:'R',watch_id:'S',request_sha256:'d'.repeat(64),url:'http://example.test/file',
   conditions:[{op:'contains',value:'new'}],watch_until:new Date(now+180).toISOString(),interval_ms:30,timeout_ms:100};
 let call=0;
 const result=await runWatch(request,async()=>{const n=call++; await new Promise(r=>setTimeout(r,n===0?70:2)); return new Response('old');});
 assert.equal(result.t_ms_basis,'request_start');
 assert.deepEqual(result.polls.map(p=>p.t_ms),result.polls.map(p=>p.t_ms).slice().sort((a,b)=>a-b));
 assert.ok(result.poll_count>=3);
});
