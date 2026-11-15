// Windows variant of the real shared wizard. No installers or network services run.
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const {spawnSync}=require('node:child_process');const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const fixture=spawnSync(process.argv[2]||'/opt/homebrew/bin/python3.12',['-c',`import json, tempfile, os
from unittest.mock import patch
from installer import windows_core as w
import kienzledoku_config as c
with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,LOCALAPPDATA=d,HF_TOKEN='hf_synthetic',HF_HOME=d), patch.object(c,'load',return_value=c.defaults()), patch.object(c,'read_commander_token',return_value=''):
 hw=w.hardware(dict(previous={},hardware=dict(Build=26100,Architecture='AMD64',RamBytes=64*2**30,Gpus=[dict(Index=0,Name='RTX 3090',VramMiB=24576)],Addresses=[dict(IPAddress='10.0.83.50')])) )
 b=w.bootstrap(hw);b['csrf']='synthetic';b['production_key']=True;b['prompt_encoding_repaired']=True
 b['defaults'].update(cache_directory='C:\\\\Models',install_directory='C:\\\\Programs\\\\kienzledoku Server')
 print(json.dumps(b))
`],{cwd:root,encoding:'utf8'});
assert.equal(fixture.status,0,fixture.stderr);const bootstrap=JSON.parse(fixture.stdout);
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let sent=null;let status=0;let fail=false;const messages=[];
 await page.exposeFunction('nativeTestMessage',m=>messages.push(m));
 await page.addInitScript(()=>{window.chrome=window.chrome||{};window.chrome.webview={postMessage:m=>window.nativeTestMessage(m)};});
 await page.route('http://127.0.0.1:18772/**',async route=>{
  const u=new URL(route.request().url()),endpoint=u.pathname;let data={};
  if(endpoint==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'installer/ui.html'))});
  if(endpoint.startsWith('/assets/'))return route.fulfill({contentType:endpoint.endsWith('.svg')?'image/svg+xml':'image/png',body:fs.readFileSync(path.join(root,endpoint.endsWith('.svg')?'assets':'docs/images',path.basename(endpoint)))});
  if(endpoint==='/api/bootstrap')data=bootstrap;
  else if(endpoint==='/api/validate'){sent=route.request().postDataJSON();data={summary:['Commander prüfen','Client einrichten'],download_bytes:0};}
  else if(endpoint==='/api/install'){sent=route.request().postDataJSON();status=0;data={started:true};}
  else if(endpoint==='/api/status'){status++;data=fail?{running:false,error:'Synthetischer Update-Konflikt',message:'Aufnahmefenster schließen',progress:5,logs:['Update-Sperre erkannt']}:{running:status<3,done:status>=3,progress:status*33,can_cancel:false,message:'Client und VAD prüfen',logs:['Client prüfen'],client_installed:true,launch_url:'kienzledoku://record?kontextId=${kontextId}&fhirBasisUrl=${fhirBasisUrl}&oAuthToken=${oAuthToken}'};}
  else if(endpoint==='/api/probe')data={fields:['anamnese','befund','ekg','sonografie','therapie','prozedere','notiz'],prompt:'REMOTE PROMPT',profiles:[{label:'Gründlich',model_label:'Gemma 4 12B Q8'}]};
  else if(endpoint==='/api/uninstall')data={client:true,server:true,models:true,settings:true,unsafe:[]};
  else throw Error('Unexpected endpoint '+endpoint);
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto('http://127.0.0.1:18772/');await page.locator('#loading').waitFor({state:'detached'});
 assert.match(await page.locator('.brand').textContent(),/Windows/);
 assert.equal(await page.locator('input[name=mode]:checked').inputValue(),'client');
 await page.locator('#next').click();
 assert.equal(await page.locator('#commander_url').inputValue(),'http://10.0.83.140:8185');
 assert.equal(await page.locator('input[id*=asr_url],input[id*=diarization_url],input[id*=llm_url]').count(),1); // only remote Commander, hidden for client
 await page.locator('#next').click();assert.equal(await page.locator('#local-model-area').isVisible(),false);
 await page.locator('#next').click();await page.locator('#probe-server').click();await page.waitForFunction(()=>document.querySelector('#prompt').value==='REMOTE PROMPT');
 await page.locator('#next').click();await page.locator('#next').click();
 await page.locator('#install-finished').waitFor({state:'visible'});assert.equal(sent.mode,'client');
 await page.locator('#copy-launch-url').count().then(async count=>{if(count)await page.locator('#copy-launch-url').click();else await page.locator('[data-copy-target="launch-url"]').click();});
 assert(!messages.includes('installer-close'),'Copy must not close the wizard');
 await page.locator('#finish-close').click();assert(messages.includes('installer-close'));
 // Combined installation with exactly one resident model and all three active grades.
 await page.reload();await page.locator('#loading').waitFor({state:'detached'});await page.locator('input[name=mode][value=combined]').check();
 await page.locator('#next').click();await page.locator('input[name=network][value=lan]').check();
 await page.locator('#next').click();
 for(const id of ['gemma12-q8','27b-q4'])await page.locator('#model-list input[value="'+id+'"]').check();
 await page.locator('input[name=memory_mode][value=parallel]').check();assert.equal(await page.locator('#parallel_model').inputValue(),'gemma12-q8');
 await page.locator('#default_model').selectOption('gemma12-q8');await page.locator('#diarization_mode').selectOption('with_asr');
 assert.equal(await page.locator('#hf_token').inputValue(),'hf_synthetic');
 await page.locator('#windows-advanced summary').click();await page.locator('#wsl_ram_gib').selectOption('28');
 await page.screenshot({path:'/private/tmp/kienzledoku-win172-wizard.png'});
 await page.locator('#next').click();assert.equal(await page.locator('#prompt-encoding-notice').isVisible(),true);
 await page.locator('#prompt').fill('Vorläufige Änderung');await page.locator('#reset-prompt').click();assert.equal(await page.locator('#prompt').inputValue(),bootstrap.default_prompt);assert((await page.locator('#prompt').inputValue()).includes('ausschließlich'));
 await page.locator('#prompt').fill('Äußere Befunde: Übelkeit, Größe – vollständig dokumentieren.');await page.locator('#field-list input[value=ekg]').check();
 await page.locator('#next').click();
 assert.equal(sent.mode,'combined');assert.equal(sent.parallel_model,'gemma12-q8');assert.equal(sent.default_model,'gemma12-q8');assert.equal(sent.wsl_ram_gib,28);assert.equal(sent.diarization_mode,'with_asr');assert.equal(sent.quality_models.sehr_gruendlich,'27b-q4');assert.equal(sent.prompt,'Äußere Befunde: Übelkeit, Größe – vollständig dokumentieren.');assert(sent.fields.includes('ekg'));
 fail=true;await page.locator('#next').click();await page.locator('#retry-install').waitFor({state:'visible'});assert.match(await page.locator('#install-error').textContent(),/Update-Konflikt/);
 await page.locator('#retry-install').click();assert.equal(await page.locator('#prompt').inputValue(),'Äußere Befunde: Übelkeit, Größe – vollständig dokumentieren.');
 fail=false;await page.locator('#next').click();await page.locator('#install-finished').waitFor({state:'visible'});
 assert.deepEqual(errors,[]);console.log('PASS Windows shared wizard: client, combined, model grades, tokens, progress, failure/retry, copy/close');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
