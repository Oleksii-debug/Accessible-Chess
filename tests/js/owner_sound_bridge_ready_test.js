'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('web/stage1_release_bootstrap.js','utf8');
const controls = new Map();
for (const id of ['move-error-announcements','sound-enabled','sound-newgame-animation','sound-volume','sound-tick-policy','sound-tick-last-seconds','sound-low-time-policy','sound-low-time-seconds','sound-settings-status']) {
  controls.set(id,{disabled:false,checked:false,value:'',textContent:''});
}
let bridge = null, reads = 0;
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
  assert(controls.get('sound-enabled').disabled);
  bridge = {
    get_state:async()=>({}),
    get_move_feedback_settings:async()=>({ok:true,enabled:false}),
    get_sound_settings:async()=>{
      reads++;
      return {ok:true,enabled:true,newGameAnimation:true,volume:80,tickPolicy:'my_turn',tickLastSeconds:0,lowTimePolicy:'my_turn',lowTimeSeconds:30};
    },
  };
  await context.markReady();
  assert.equal(reads,1,'pywebviewready must retry the initial unavailable bridge');
  assert.equal(controls.get('sound-enabled').checked,true);
  assert.equal(controls.get('sound-volume').value,'80');
  for(const [id,control] of controls) assert(!control.disabled,id+' stayed disabled');
  assert.equal(context.document.body.dataset.stage1AppReady,'true');
  console.log('Owner sound settings late bridge recovery: PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
