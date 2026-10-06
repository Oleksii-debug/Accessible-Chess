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
vm.runInContext(source.slice(source.indexOf('async function loadMoveFeedbackSettings()'),source.indexOf('function applySoundLanguage()')),context);
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
