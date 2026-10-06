'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('web/stage1_release_bootstrap.js','utf8');
const controls = new Map();
for (const id of ['move-error-announcements','sound-enabled','sound-newgame-animation','sound-volume','sound-tick-policy','sound-tick-last-seconds','sound-low-time-policy','sound-low-time-seconds','sound-settings-status']) {
  controls.set(id,{disabled:false,checked:false,value:'',textContent:''});
}
let bridge = null, reads = 0, failSoundRead = false;
const context = {
  byId:id=>controls.get(id), api:()=>bridge, text:()=>({unavailable:'Unavailable'}),
  document:{body:{dataset:{}}},
  stabilizeMoveEntryUiaSemantics(){},stabilizeBoardUiaSemantics(){},
  settleMoveEntryOnScreen:async()=>{},publishMoveEntryExposureState(){},
  requestAnimationFrame:fn=>fn(),soundStateLoadPromise:Promise.resolve(),
};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('let currentSoundState = null;'),source.indexOf('function applySoundLanguage()')),context);
vm.runInContext(source.slice(source.indexOf('async function markReady()'),source.indexOf('\ninstallMoveFocusPolicy();')),context);
(async()=>{
  await context.loadSoundState();
  for(const id of ['sound-enabled','sound-newgame-animation','sound-volume','sound-tick-policy','sound-tick-last-seconds','sound-low-time-policy','sound-low-time-seconds']) {
    assert(controls.get(id).disabled,id+' was active before canonical sound state loaded');
  }
  bridge = {
    get_state:async()=>({}),
    get_move_feedback_settings:async()=>({ok:true,enabled:false}),
    get_sound_settings:async()=>{
      reads++;
      if(failSoundRead) throw new Error('private sound read failure');
      return {ok:true,enabled:true,newGameAnimation:true,volume:80,tickPolicy:'my_turn',tickLastSeconds:0,lowTimePolicy:'my_turn',lowTimeSeconds:30};
    },
  };
  await context.markReady();
  assert.equal(reads,1,'pywebviewready must retry the initial unavailable bridge');
  assert.equal(controls.get('sound-enabled').checked,true);
  assert.equal(controls.get('sound-volume').value,'80');
  for(const [id,control] of controls) assert(!control.disabled,id+' stayed disabled');
  assert.equal(context.document.body.dataset.stage1AppReady,'true');

  const feedback = controls.get('move-error-announcements');
  feedback.checked = true;
  bridge.get_move_feedback_settings = async()=>({ok:false,enabled:true});
  await context.loadMoveFeedbackSettings();
  assert.equal(feedback.checked,false,'non-authoritative feedback read must clear stale enabled state');
  assert.equal(feedback.disabled,true,'non-authoritative feedback read must remain disabled');
  feedback.checked = true;
  bridge.get_move_feedback_settings = async()=>{throw new Error('private feedback read failure');};
  await context.loadMoveFeedbackSettings();
  assert.equal(feedback.checked,false,'failed feedback reload must clear stale enabled state');
  assert.equal(feedback.disabled,true,'failed feedback reload must remain disabled');

  let resolveFeedbackWrite = null;
  bridge.get_move_feedback_settings = async()=>({ok:true,enabled:false});
  bridge.set_move_error_announcements = ()=>new Promise(resolve=>{resolveFeedbackWrite=resolve;});
  feedback.checked = true;
  const pendingFeedbackWrite = context.persistMoveFeedbackSetting(feedback,true);
  assert.equal(feedback.disabled,true,'feedback control must be disabled while persistence is unresolved');
  resolveFeedbackWrite({ok:true,enabled:true});
  assert.equal(await pendingFeedbackWrite,true,'authoritative feedback write should succeed');
  assert.equal(feedback.checked,true,'authoritative persisted feedback state must be reflected');
  assert.equal(feedback.disabled,false,'authoritative feedback write must re-enable the control');

  bridge.set_move_error_announcements = async()=>({ok:false,enabled:true});
  bridge.get_move_feedback_settings = async()=>({ok:true,enabled:false});
  feedback.checked = true;
  assert.equal(
    await context.persistMoveFeedbackSetting(feedback,true),
    false,
    'non-authoritative feedback write must fail closed',
  );
  assert.equal(feedback.checked,false,'failed feedback write must restore canonical persisted state');
  assert.equal(feedback.disabled,false,'successful canonical reread may re-enable the feedback control');

  bridge.set_move_error_announcements = async()=>{throw new Error('private feedback write failure');};
  bridge.get_move_feedback_settings = async()=>{throw new Error('private feedback read failure');};
  feedback.checked = true;
  assert.equal(
    await context.persistMoveFeedbackSetting(feedback,true),
    false,
    'feedback write exception must fail closed',
  );
  assert.equal(feedback.checked,false,'failed feedback write+reload must clear stale requested state');
  assert.equal(feedback.disabled,true,'failed feedback write+reload must leave the control disabled');

  const canonicalSoundState = overrides => Object.assign({
    ok:true,
    enabled:true,
    newGameAnimation:true,
    volume:80,
    tickPolicy:'my_turn',
    tickLastSeconds:0,
    lowTimePolicy:'my_turn',
    lowTimeSeconds:30,
    message:'',
  }, overrides || {});

  bridge.get_move_feedback_settings = async()=>({ok:true,enabled:false});
  bridge.get_sound_settings = async()=>canonicalSoundState({ok:false,enabled:false});
  assert.equal(await context.loadSoundState(),false,'ok:false sound read must not publish state');
  assert.equal(vm.runInContext('currentSoundState',context),null);
  for(const id of ['sound-enabled','sound-newgame-animation','sound-volume','sound-tick-policy','sound-tick-last-seconds','sound-low-time-policy','sound-low-time-seconds']) {
    assert(controls.get(id).disabled,id+' was enabled by non-authoritative sound state');
  }
  assert.equal(controls.get('sound-settings-status').textContent,'Unavailable');

  bridge.get_sound_settings = async()=>canonicalSoundState();
  assert.equal(await context.loadSoundState(),true,'authoritative sound state should recover controls');
  for(const id of ['sound-enabled','sound-newgame-animation','sound-volume','sound-tick-policy','sound-tick-last-seconds','sound-low-time-policy','sound-low-time-seconds']) {
    assert(!controls.get(id).disabled,id+' stayed disabled after authoritative sound reload');
  }

  let resolveSoundWrite = null;
  bridge.set_sound_volume = ()=>new Promise(resolve=>{resolveSoundWrite=resolve;});
  controls.get('sound-volume').value = '35';
  const pendingSoundWrite = context.persistSoundSetting('set_sound_volume',35);
  assert.equal(vm.runInContext('currentSoundState',context),null,'pending sound write must revoke stale state');
  for(const id of ['sound-enabled','sound-newgame-animation','sound-volume','sound-tick-policy','sound-tick-last-seconds','sound-low-time-policy','sound-low-time-seconds']) {
    assert(controls.get(id).disabled,id+' stayed interactive during sound persistence');
  }
  resolveSoundWrite(canonicalSoundState({volume:35,message:'Volume 35'}));
  const soundWriteResult = await pendingSoundWrite;
  assert.equal(soundWriteResult.ok,true);
  assert.equal(controls.get('sound-volume').value,'35');
  for(const id of ['sound-enabled','sound-newgame-animation','sound-volume','sound-tick-policy','sound-tick-last-seconds','sound-low-time-policy','sound-low-time-seconds']) {
    assert(!controls.get(id).disabled,id+' stayed disabled after authoritative sound write');
  }

  bridge.set_sound_volume = async()=>canonicalSoundState({ok:false,volume:5,message:'write refused'});
  bridge.get_sound_settings = async()=>canonicalSoundState({volume:35});
  controls.get('sound-volume').value = '5';
  const refusedSoundWrite = await context.persistSoundSetting('set_sound_volume',5);
  assert.equal(refusedSoundWrite.ok,false);
  assert.equal(refusedSoundWrite.message,'write refused');
  assert.equal(controls.get('sound-volume').value,'35','ok:false write must restore canonical sound state');
  assert.equal(vm.runInContext('currentSoundState.volume',context),35);

  bridge.set_sound_volume = async()=>{throw new Error('private sound write failure');};
  controls.get('sound-volume').value = '10';
  const failedSoundWrite = await context.persistSoundSetting('set_sound_volume',10);
  assert.equal(failedSoundWrite.ok,false);
  assert.equal(controls.get('sound-volume').value,'35','thrown sound write must restore canonical state');
  assert.equal(vm.runInContext('currentSoundState.volume',context),35);

  bridge.get_sound_settings = async()=>{
    reads++;
    if(failSoundRead) throw new Error('private sound read failure');
    return canonicalSoundState();
  };
  failSoundRead = true;
  const failedReload = context.loadSoundState();
  assert.equal(
    vm.runInContext('currentSoundState', context),
    null,
    'a reload in progress must revoke stale sound timing authority before awaiting the bridge',
  );
  await failedReload;
  assert.equal(
    vm.runInContext('currentSoundState', context),
    null,
    'a failed canonical reload must not retain stale sound timing authority',
  );
  for(const id of ['sound-enabled','sound-newgame-animation','sound-volume','sound-tick-policy','sound-tick-last-seconds','sound-low-time-policy','sound-low-time-seconds']) {
    assert(controls.get(id).disabled,id+' stayed active after canonical sound-state read failed');
  }
  assert.equal(controls.get('sound-settings-status').textContent,'Unavailable');
  console.log('Owner sound settings late bridge recovery: PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
