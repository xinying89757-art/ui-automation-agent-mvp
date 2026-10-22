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
