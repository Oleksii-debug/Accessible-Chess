"use strict";
/* Genuine YouTube IFrame; no download/cache/extraction of provider video. */
const http=require("node:http"),fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict");
const {chromium}=require("playwright");
const id=process.argv[2];
if(!/^[A-Za-z0-9_-]{11}$/.test(id||""))throw Error("eleven-char video ID required");
const adapter=fs.readFileSync(path.join(__dirname,"../../web/youtube_iframe_playback_adapter.js"));
const html=[
'<!doctype html><html lang="uk"><meta charset="utf-8"><h1>YouTube IFrame live test</h1>',
'<div id="player"></div><button id="play">Відтворити</button><button id="pause">Пауза</button>',
'<p id="status" role="status" aria-live="polite">Немає зєднання</p><script src="/adapter.js"></script>',
'<script>',
'window.snapshots=[];window.playerAdapter=null;window.providerStartError=null;',
'window.onYouTubeIframeAPIReady=function(){try{',
'window.playerAdapter=new AccessibleChessYouTubeIframePlayback.YouTubeIframePlaybackAdapter({',
'YT:window.YT,element:"player",source:'+JSON.stringify(id)+',origin:window.location.origin,',
'onSnapshot:function(s){window.snapshots.push(s);document.getElementById("status").textContent=s.ok?s.playbackState:"provider error "+s.errorCode;}});',
'}catch(error){window.providerStartError=String(error).slice(0,180);}};',
'document.getElementById("play").onclick=function(){try{window.playerAdapter.play();}catch(e){window.controlError=String(e).slice(0,180);}};',
'document.getElementById("pause").onclick=function(){try{window.playerAdapter.pause();}catch(e){window.controlError=String(e).slice(0,180);}};',
'const script=document.createElement("script");script.src="https://www.youtube.com/iframe_api";',
'script.onerror=function(){window.providerStartError="Official YouTube IFrame network failure";};',
'document.head.appendChild(script);',
'</script></html>'
].join("");
async function main(){
 let server=null,browser=null;
 try{
  server=http.createServer((req,res)=>{
   res.setHeader("Cache-Control","no-store");
   res.setHeader("Referrer-Policy","strict-origin-when-cross-origin");
   if(req.url==="/adapter.js"){res.setHeader("Content-Type","text/javascript");res.end(adapter);}
   else if(req.url==="/"){res.setHeader("Content-Type","text/html; charset=utf-8");res.end(html);}
   else {res.writeHead(404);res.end("Not found");}
  });
  await new Promise((resolve,reject)=>{server.once("error",reject);server.listen(0,"127.0.0.1",resolve);});
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({locale:"uk-UA"});
  await page.goto("http://127.0.0.1:"+server.address().port+"/",{waitUntil:"domcontentloaded",timeout:25000});
  await page.waitForFunction(()=>window.providerStartError||window.snapshots.some(s=>s.ready===true||s.ok===false),null,{timeout:45000});
  const initial=await page.evaluate(()=>({error:window.providerStartError,events:window.snapshots.slice(-10)}));
  if(initial.error)throw Error("provider script unavailable");
  if(initial.events.some(s=>s.ok===false))throw Error("provider refused embedding");
  assert(initial.events.some(s=>s.ready===true),"no genuine provider READY");
  await page.locator("#player iframe").waitFor({state:"attached",timeout:12000});
  await page.locator("#play").click();
  await page.waitForFunction(()=>window.controlError||window.snapshots.some(s=>s.ok===false||s.playbackState==="playing"),null,{timeout:35000});
  const played=await page.evaluate(()=>({error:window.controlError,events:window.snapshots.slice(-15)}));
  if(played.error||played.events.some(s=>s.ok===false))throw Error("provider play refused");
  const start=played.events.filter(s=>s.playbackState==="playing").at(-1);
  if(!start)throw Error("no provider PLAYING state");
  await page.waitForTimeout(2500);
  const later=await page.evaluate(()=>window.playerAdapter.refresh());
  if(!later.ok||later.positionMs<=start.positionMs)throw Error("provider clock did not advance");
  await page.locator("#pause").click();
  console.log(JSON.stringify({evidence_class:"LIVE_YOUTUBE_IFRAME",status:"PASS",
   video_id:id,ready:true,playing:true,earlier_ms:start.positionMs,later_ms:later.positionMs,
   pause_command_sent:true,chess_timeline:"NOT_RUN",windows_nvda:"NOT_RUN"}));
 }finally{
  if(browser)await browser.close();
  if(server)await new Promise(resolve=>server.close(resolve));
 }
}
main().catch(e=>{console.error(JSON.stringify({evidence_class:"LIVE_YOUTUBE_IFRAME",status:"FAIL_OR_BLOCKED",video_id:id,
 reason:String(e&&e.message||e).slice(0,160)}));process.exitCode=1;});
