import test from 'node:test';
import assert from 'node:assert/strict';
import { checkOne, evaluate } from '../scripts/templates/remote-check.mjs';
const start=Date.parse('2026-01-01T00:00:00Z');
const check={id:'c', url:'http://example.test/file',method:'GET',timeout_ms:100,
 saved_at:new Date(start).toISOString(),earliest_check_at:new Date(start+3600000).toISOString(),
 deadline:new Date(start+7200000).toISOString(),conditions:[{op:'contains',value:'new'}]};
const response=(body,status=200)=>async()=>new Response(body,{status});
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
 const body='safe target person@example.com eyJabcdefghijk.abcdefghijk.abcdefghijk 13812345678';
 const result=await checkOne({...check,conditions:[{op:'contains',value:'safe target'}]},response(body),()=>start+1000);
 assert.equal(result.evidence.length,1); assert.ok(result.evidence[0].excerpt.length<=2000);
 assert.doesNotMatch(result.evidence[0].excerpt,/person@example\.com|eyJabcdefghijk|13812345678/);
});
