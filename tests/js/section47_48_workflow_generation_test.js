"use strict";
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
class Node{
  constructor(tag="div"){this.tag=tag;this.id="";this.parentNode=null;this.children=[];this.attrs={};
    this.listeners={};this.textContent="";this.value="";this.disabled=false;}
  appendChild(child){child.parentNode=this;this.children.push(child);return child;}
  insertBefore(child){return this.appendChild(child);}
  replaceChildren(...children){this.children=[];children.forEach(c=>this.appendChild(c));}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(name,callback){this.listeners[name]=callback;}
  focus(){this.focused=true;}
}
const parent=new Node(), main=new Node();
main.parentNode=parent;
const document={
  documentElement:{lang:"uk"},head:new Node("head"),
  getElementById:(id)=>id==="main-content"?main:null,
  createElement:(tag)=>new Node(tag)
};
const pending=[];
const playbackRender=[];
const notifications=[];
const sourceL={ok:true,sourceId:"local:sha256:aaaaaaaa",sourceTitle:"Local A",
 providerKind:"browser_local",browserSourceUrl:"file:///C:/chess-original.webm",
 player:{ok:true,sourceId:"local:sha256:aaaaaaaa"}};
const sourceY={ok:true,sourceId:"youtube:k4BS-4O1iI0",sourceTitle:"YouTube B",
 providerKind:"youtube",player:{ok:true,sourceId:"youtube:k4BS-4O1iI0"}};
class LocalAdapter {
  constructor(options){this.options=options;LocalAdapter.last=this;LocalAdapter.instances.push(this);}
  destroy(){this.destroyed=true;}
  snapshot(){return {sourceId:this.options.sourceId,positionMs:2000,durationMs:10000,playbackState:"playing"};}
  play(){}pause(){}seek(){}refresh(){}
}
LocalAdapter.instances=[];
class YouTubeAdapter {
  constructor(options){this.options=options;YouTubeAdapter.last=this;}
  destroy(){this.destroyed=true;}
  snapshot(){return {providerId:"youtube_iframe_v1",sourceId:sourceY.sourceId,
    ok:true,ready:true,positionMs:5000,durationMs:10000,playbackState:"playing"};}
  play(){}pause(){}seek(){}refresh(){}
}
const pywebview={api:{
  media_workflow_open_local:()=>Promise.resolve(sourceL),
  media_workflow_open_pasted:()=>Promise.resolve(sourceY),
  media_workflow_sync_playback:(id,pos,duration,state)=>new Promise(resolve=>{
    pending.push({id,pos,duration,state,resolve});
  }),
  media_workflow_command:()=>Promise.resolve(sourceY),
}};
const globalObject={
  document,pywebview,YT:{Player:function(){}},
  AccessibleChessRecordedMediaPlayer:{render:(_mount,state)=>playbackRender.push(state.sourceId)},
  AccessibleChessLocalVideoPlayback:{BrowserLocalVideoPlaybackAdapter:LocalAdapter},
  AccessibleChessYouTubeIframePlayback:{YouTubeIframePlaybackAdapter:YouTubeAdapter},
  location:{origin:"http://127.0.0.1:5658"},
  setTimeout:(cb)=>cb(),
};
globalObject.window=globalObject;
vm.runInNewContext(fs.readFileSync("web/version2_media_user_workflow.js","utf8"),globalObject,
 {filename:"version2_media_user_workflow.js"});
const api=globalObject.AccessibleChessSection20MediaWorkflow;
assert(api,"canonical Media workflow must install");
async function tick(){await Promise.resolve();await Promise.resolve();await Promise.resolve();}
(async()=>{
  assert.equal(await api.openLocal(),true,"local file should open");
  const stale=LocalAdapter.last;
  assert.equal(api.currentProviderKind(),"browser_local");
  stale.options.onSnapshot(stale.snapshot());
  assert.equal(pending.length,1,"first timing observation must reach canonical host");
  const old=pending.shift();
  const currentSourceText="k4BS-4O1iI0";
  const sourceInput=parent.children.flatMap(n=>n.children).find(n=>n.id==="section20-media-source");
  assert(sourceInput,"native media source input missing");
  sourceInput.value=currentSourceText;
  assert.equal(await api.openPasted(),true,"new YouTube source should open");
  assert.equal(api.currentProviderKind(),"youtube");
  assert(stale.destroyed,"old local adapter should be destroyed");
  const before=playbackRender.length;
  stale.options.onSnapshot(stale.snapshot());
  assert.equal(pending.length,0,"stale callback must not reach native host");
  old.resolve(sourceL);
  await tick();
  assert.equal(playbackRender.length,before,"old in-flight native reply must not repaint active source");
  assert.equal(api.currentProviderKind(),"youtube");
  const remote=YouTubeAdapter.last;
  remote.options.onSnapshot({providerId:"youtube_iframe_v1",
    sourceId:sourceY.sourceId,ok:false,ready:true,errorCode:101,
    positionMs:0,durationMs:null,playbackState:"unstarted"});
  assert.equal(pending.length,0,"provider denial must never move native chess clock");
  remote.options.onSnapshot({providerId:"youtube_iframe_v1",
    sourceId:sourceY.sourceId,ok:false,ready:true,errorCode:153,
    positionMs:0,durationMs:null,playbackState:"unstarted"});
  assert.equal(pending.length,0,"missing client identity must not move chess clock");
  remote.options.onSnapshot({providerId:"youtube_iframe_v1",
    sourceId:sourceY.sourceId,ok:true,ready:false,errorCode:null,
    positionMs:0,durationMs:null,playbackState:"unstarted"});
  assert.equal(pending.length,0,"not-ready IFrame must not move chess clock");
  remote.options.onSnapshot({providerId:"youtube_iframe_v1",
    sourceId:sourceY.sourceId,ok:true,ready:true,errorCode:null,
    positionMs:3000,durationMs:10000,playbackState:"playing"});
  assert.equal(pending.length,1,"ready authorized IFrame should publish timeline clock");
  const synced=pending.shift();
  assert.equal(synced.id,sourceY.sourceId);
  assert.equal(synced.pos,3000);
  synced.resolve(sourceY);
  await tick();
  assert.equal(api.currentProviderKind(),"youtube");
  assert(playbackRender.at(-1)===sourceY.sourceId);
  api.destroyProvider();
  remote.options.onSnapshot({providerId:"youtube_iframe_v1",
    sourceId:sourceY.sourceId,ok:true,ready:true,errorCode:null,
    positionMs:4000,durationMs:10000,playbackState:"playing"});
  assert.equal(pending.length,0,"destroyed provider callback must be ignored");
  console.log("section47_48_workflow_generation_test: PASS");
})().catch(e=>{console.error(e);process.exitCode=1;});
