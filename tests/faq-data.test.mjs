import test from 'node:test';
import assert from 'node:assert/strict';
import { addFaq } from '../assets/playwright-runner/flows/faq-data.mjs';
const rule={method:'POST',path:'/faq/edit',fields:{id:'record',title:'title',content:'content'}};
function mockFrame(fields, fail=false) {
 const sent=[];
 const request={post:async(url,options)=>{sent.push({url,options});if(fail)throw Error('private-local-placeholder');return {ok:()=>true}}};
 const node={getByRole:()=>node,click:async()=>{},waitFor:async()=>{},page:()=>({request}),
   evaluate:async()=>({origin:'https://example.test',fields:structuredClone(fields)})};
 return {frame:{locator:()=>node},sent};
}
test('FAQ create uses fresh protected fields in memory and preserves exact answer text as escaped HTML',async()=>{
 const {frame,sent}=mockFrame({record:'',form_token_value:'private-local-placeholder',tenant:'configured-scope'});
 await addFaq(frame,'Question','A < B & C',rule);
 assert.equal(sent[0].url,'https://example.test/faq/edit');
 assert.equal(sent[0].options.form.content,'<p>A &lt; B &amp; C</p>');
 assert.equal(sent[0].options.form.form_token_value,'private-local-placeholder');
 assert.equal(sent[0].options.form.tenant,'configured-scope');
});
test('FAQ create refuses to overwrite an existing record and never exposes a transport error',async()=>{
 const existing=mockFrame({record:'existing'});
 await assert.rejects(addFaq(existing.frame,'Q','A',rule),/existing record/);assert.equal(existing.sent.length,0);
 const broken=mockFrame({record:''},true);
 await assert.rejects(addFaq(broken.frame,'Q','A',rule),error=>error.message==='UIA_SETUP_FAILED: FAQ create transport error');
});
