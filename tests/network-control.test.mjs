import test from 'node:test';
import assert from 'node:assert/strict';
import { delayRequests } from '../assets/playwright-runner/flows/network-control.mjs';
test('only matching method is delayed/counts; release and disposal remove the route',async()=>{
 let handler,matcher,removed=false,continued=0,fallback=0;
 const page={route:async(m,h)=>{matcher=m;handler=h},unroute:async(m,h)=>{removed=m===matcher&&h===handler}};
 const control=await delayRequests(page,{path:'/save',method:'POST'},10000);
 assert.ok(matcher(new URL('https://example.test/save?ignored=1')));
 assert.equal(matcher(new URL('https://example.test/other')),false);
 const route=method=>({request:()=>({method:()=>method}),continue:async()=>{continued++},fallback:async()=>{fallback++}});
 await handler(route('GET'));assert.equal(fallback,1);assert.equal(control.count(),0);
 const pending=handler(route('POST'));assert.equal(control.count(),1);assert.equal(continued,0);
 control.release();await pending;assert.equal(continued,1);
 await control.dispose();assert.ok(removed);
});
test('bounded delay rejects invalid input before touching the browser',async()=>{
 for(const delay of [-1,0,30001,1.5]) await assert.rejects(delayRequests({}, {path:'/x',method:'POST'},delay));
});
import { chromium } from '../assets/playwright-runner/node_modules/@playwright/test/index.mjs';
import { observeOccurrences } from '../assets/playwright-runner/flows/network-control.mjs';
test('transient visible results are counted after removal, and duplicate appearances count twice',async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage();await page.setContent('<div id="messages"></div>');
  const observation=await observeOccurrences(page,'Saved');
  await page.locator('#messages').evaluate(el=>{el.innerHTML='<div><span>Saved</span></div>'});
  assert.equal(await observation.count(),1);
  await page.locator('#messages').evaluate(el=>{el.innerHTML=''});
  assert.equal(await observation.count(),1);
  await page.locator('#messages').evaluate(el=>{el.innerHTML='<span>Saved</span>'});
  assert.equal(await observation.count(),2);await observation.dispose();
 } finally {await browser.close();}
});
import http from 'node:http';
import { doubleClick, attemptClick } from '../assets/playwright-runner/flows/network-control.mjs';
test('real route interception preserves in-progress state and double-click emits exactly one request',async()=>{
 let received=0;
 const server=http.createServer((request,response)=>{
  if(request.url==='/save'){received++;response.end('saved');return;}
  response.setHeader('Content-Type','text/html');
  response.end(`<button id="save">Save</button><a id="cancel">Cancel</a><div id="dialog">Dialog</div><div id="result"></div>
  <script>let busy=false;save.onclick=async()=>{if(busy)return;busy=true;save.disabled=true;save.textContent='Loading';await fetch('/save',{method:'POST'});result.textContent='Saved';dialog.hidden=true};cancel.onclick=()=>{if(!busy)dialog.hidden=true};</script>`);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();await page.goto('http://127.0.0.1:'+server.address().port);
  const counter=await delayRequests(page,{path:'/save',method:'POST'},10000);
  await doubleClick(page,page.locator('#save'));
  await page.waitForFunction(()=>document.querySelector('#save').disabled);
  assert.equal(await page.locator('#save').innerText(),'Loading');
  await attemptClick(page,page.locator('#cancel'));
  assert.ok(await page.locator('#dialog').isVisible());assert.equal(counter.count(),1);assert.equal(received,0);
  counter.release();await page.locator('#result').filter({hasText:'Saved'}).waitFor();
  assert.equal(counter.count(),1);assert.equal(received,1);await counter.dispose();
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
});
