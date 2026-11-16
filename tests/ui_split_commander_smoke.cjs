// Shared real wizard; synthetic bootstrap, no installation or patient data.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true});try{
for(const platform of ['macos','windows']){
 const bootstrap=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/installer_bootstrap.json')));
 bootstrap.platform=platform;bootstrap.defaults.remote_diar_url='';bootstrap.defaults.remote_diar_token='';bootstrap.defaults.asr_model='large-v3';
 bootstrap.hardware.lan_addresses=['192.0.2.1'];bootstrap.hardware.gpus=[];
 let sent;const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://127.0.0.1:18773/**',async route=>{const url=new URL(route.request().url());let data={};
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../installer/ui.html'))});
  if(url.pathname.startsWith('/assets/'))return route.fulfill({status:204,body:''});
  if(url.pathname==='/api/bootstrap')data=bootstrap;
  if(url.pathname==='/api/validate'){sent=route.request().postDataJSON();data={summary:['Synthetic validation'],download_bytes:0};}
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto('http://127.0.0.1:18773/');await page.locator('#loading').waitFor({state:'detached'});
 await page.locator('input[name=mode][value=server]').check();
 await page.locator('input[name=server_role][value=asr]').check();
 await page.locator('#next').click();
 await page.locator('#remote_llm_url').fill('http://192.0.2.2:8185');
 assert.match(await page.locator('#remote_llm_url').getAttribute('placeholder'),/8185/);
 await page.locator('#next').click();assert.equal(await page.locator('#local-model-area').isVisible(),false);
 await page.locator('#asr_model').selectOption('turbo-int8');
 await page.locator('#remote_diar_url').fill('http://192.0.2.3:8185');
 await page.locator('#remote_diar_token').fill('synthetic');
 assert.equal(await page.locator('#diarization-mode-field').isVisible(),false);
 await page.locator('#next').click();await page.locator('#next').click();
 assert.equal(sent.server_role,'asr');assert.equal(sent.asr_model,'turbo-int8');assert.equal(sent.remote_diar_url,'http://192.0.2.3:8185');assert.equal(sent.remote_diar_token,'synthetic');assert.equal(sent.auth_enabled,false);
 await page.locator('#back').click();await page.locator('#back').click();
 await page.locator('#remote_diar_url').fill('http://192.0.2.4:8185');assert.equal(await page.locator('#remote_diar_token').inputValue(),'');
 assert.deepEqual(errors,[]);await page.close();console.log('PASS '+platform+': split LLM/diarization, Turbo choice, hidden local models, optional auth, token reset on changed target');
}
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
