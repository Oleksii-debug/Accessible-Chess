'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const {shellForKeymap} = require('./keymap_shell_test_support');
const html = fs.readFileSync('web/index.html', 'utf8');
const rows = JSON.parse(fs.readFileSync('web/keybindings.json', 'utf8')).actions;
const shell = shellForKeymap(rows, 'uk');
let listener;
const calls = [];
const settingsSection = {hidden: false};
shell.capture = null;
shell.document.addEventListener = (name, fn) => { assert.equal(name, 'keydown'); listener = fn; };
shell.window = {getSelection: () => ({toString: () => ''})};
shell.resolveBinding = async (chord, context) => {
  calls.push(['resolve', chord, context]);
  const action = rows.find(row => row.binding === chord && row.registryContext === context) || rows.find(row => row.binding === chord && row.registryContext === 'global');
  return action ? {actionId: action.id, context:action.registryContext} : null;
};
shell.executeAction = id => calls.push(['execute', id]);
const globalHandler = html.split('\n').find(line => line.startsWith('function projectedOwnedAction('));
vm.runInContext(globalHandler, shell);
function event(key, mods = {}, tag = 'INPUT') {
  return {key, ctrlKey:false, altKey:false, shiftKey:false, metaKey:false,
    target:{tagName:tag, closest:()=>null},
    preventDefault(){calls.push(['prevent']);}, stopPropagation(){calls.push(['stop']);}, ...mods};
}
(async () => {
  for (const tag of ['INPUT', 'TEXTAREA', 'SELECT', 'DIV']) {
    calls.length = 0;
    await listener(event('n', {ctrlKey:true}, tag));
    assert.deepEqual(calls[0], ['prevent'], 'cancel before awaiting the bridge');
    assert.deepEqual(calls[calls.length-1], ['execute', 'file.new']);
  }
  for (const key of ['1','2']) {
    calls.length = 0;
    await listener(event(key, {altKey:true}));
    assert.deepEqual(calls[0], ['prevent']);
    assert.deepEqual(calls[calls.length-1], ['execute', 'analysis.pv'+key]);
  }
  for (const [key, mods] of [['c',{ctrlKey:true}],['a',{ctrlKey:true}],['Home',{ctrlKey:true}],['x',{ctrlKey:true}],['z',{ctrlKey:true}],['e',{}]]) {
    calls.length = 0;
    await listener(event(key, mods));
    assert.equal(calls.length, 0, 'native editing must survive: '+key);
  }
  // Remaps are resolved from the same snapshot, not a hardcoded Ctrl+N override.
  shell.keymap.find(row => row.id === 'file.new').binding = 'Ctrl+Shift+N';
  rows.find(row => row.id === 'file.new').binding = 'Ctrl+Shift+N';
  calls.length = 0;
  await listener(event('n', {ctrlKey:true}));
  assert.equal(calls.length, 0);
  await listener(event('n', {ctrlKey:true,shiftKey:true}));
  assert.deepEqual(calls[calls.length-1], ['execute','file.new']);
  // Failed move keeps a readable error while speech follows the persisted checkbox.
  const spoken = [], rendered = [];
  let response = {ok:false,announcement:'Перевірте запис і позицію.',announceMoveErrors:false};
  let throwMove = false, throwRender = false;
  Object.assign(shell, {
    nextAnnouncementEvent:()=>1, api:()=>({make_move:async()=>{if(throwMove)throw new Error('private bridge failure');return response;}}),
    render:async()=>{if(throwRender)throw new Error('private render failure');}, setText:(id,text)=>rendered.push([id,text]),
    announce:text=>spoken.push(text), localizedUiText:uk=>uk,
    el:id=>id==='h-settings'?{closest:()=>settingsSection}:null,
  });
  vm.runInContext(html.split('\n').find(line=>line.startsWith('async function apiAction(')), shell);
  await shell.apiAction('make_move','nf9');
  assert.equal(spoken.length,0);
  assert.deepEqual(rendered.pop(),['move-input-error',response.announcement]);
  delete response.announceMoveErrors;
  await shell.apiAction('make_move','nf9');
  assert.equal(spoken.length,0,'missing preference must fail closed');
  response.announceMoveErrors='true';
  await shell.apiAction('make_move','nf9');
  assert.equal(spoken.length,0,'non-boolean preference must fail closed');
  response.announceMoveErrors=true;
  await shell.apiAction('make_move','nf9');
  assert.equal(spoken.length,1,'only explicit boolean true may speak a move error');
  throwMove=true;
  spoken.length=0;
  await shell.apiAction('make_move','nf9');
  assert.deepEqual(rendered.pop(),['move-input-error','Не вдалося виконати дію.']);
  assert.equal(spoken.pop(),'Не вдалося виконати дію.');
  throwMove=false;
  response={ok:true,announcement:'Зіграно: кінь f 3',announceMoveErrors:false};
  throwRender=true;
  const committed=await shell.apiAction('make_move','nf3');
  assert.equal(committed,response,'post-commit presentation failure must preserve the authoritative result');
  assert.deepEqual(rendered.pop(),['move-input-error','Хід виконано, але не вдалося оновити відображення.']);
  assert.equal(spoken.pop(),'Хід виконано, але не вдалося оновити відображення.');
  throwRender=false;
  await shell.apiAction('make_move','nf3');
  assert.deepEqual(rendered.pop(),['move-input-error','']);
  vm.runInContext(html.split('\n').find(line=>line.startsWith('function showStage1Route(')), shell);
  shell.showStage1Route('board');assert.equal(settingsSection.hidden,true);
  shell.showStage1Route('settings');assert.equal(settingsSection.hidden,false);
  shell.showStage1Route('analysis');assert.equal(settingsSection.hidden,true);
  assert(!html.includes('id="skip-link"'));
  assert(!html.includes('<h1>Accessible Chess</h1>'));
  for(const file of ['web/version2_release_bootstrap.js','web/version2_final_product_bootstrap.js']) {
    const source=fs.readFileSync(file,'utf8');
    assert(!source.includes('createElement("ul")'));
    assert(!source.includes('createElement("li")'));
    assert(source.includes('global.showStage1Route(routeId)'));
  }
  // Starting an engine game is one atomic UI transaction. While the bridge
  // request is pending, a blind keyboard user must not be able to close the
  // dialog and create an active backend game behind a stale/closed surface.
  let resolveEngineStart, engineStartCalls=0, moveInputFocus=0, startButtonFocus=0;
  const engineAnnouncements=[];
  const engineNodes={
    'engine-game-start':{disabled:false,focus:()=>{startButtonFocus+=1;}},
    'engine-game-cancel':{disabled:false},
    'engine-human-side':{value:'white'},
    'engine-level':{value:'5'},
    'engine-minutes':{value:'5'},
    'engine-increment':{value:'0'},
    'engine-game-dialog':{closeCalls:0,close(){this.closeCalls+=1;}},
    'move-input':{focus:()=>{moveInputFocus+=1;}},
  };
  shell.el=id=>engineNodes[id];
  shell.setText=()=>{};
  shell.announceUserAction=text=>engineAnnouncements.push(text);
  shell.apiAction=()=>{engineStartCalls+=1;return new Promise(resolve=>{resolveEngineStart=resolve;});};
  vm.runInContext('let engineGameStartInFlight=false,engineGameReturnFocusOnClose=false;',shell);
  vm.runInContext(html.split('\n').find(line=>line.startsWith('async function startEngineGame(')),shell);
  const enginePending=shell.startEngineGame();
  assert.equal(engineNodes['engine-game-start'].disabled,true);
  assert.equal(engineNodes['engine-game-cancel'].disabled,true);
  assert.deepEqual(engineAnnouncements,['Запуск Stockfish…'],'pending start must be announced through the shared live region');
  await shell.startEngineGame();
  assert.equal(engineStartCalls,1,'a second Start during the pending bridge request must be ignored');
  resolveEngineStart({ok:true});
  await enginePending;
  assert.equal(engineNodes['engine-game-dialog'].closeCalls,1);
  assert.equal(moveInputFocus,1);
  assert.equal(engineNodes['engine-game-start'].disabled,false);
  assert.equal(engineNodes['engine-game-cancel'].disabled,false);

  shell.apiAction=async()=>{engineStartCalls+=1;return {ok:false,announcement:'start failed'};};
  await shell.startEngineGame();
  assert.equal(startButtonFocus,1,'failed start must keep keyboard focus inside the dialog');
  assert.equal(engineNodes['engine-game-start'].disabled,false);
  assert.equal(engineNodes['engine-game-cancel'].disabled,false);

  // Closing keyboard settings must retire shortcut-capture state. Otherwise
  // the capture-phase document handler would continue consuming keys while
  // the dialog is already hidden.
  assert(
    html.includes("el('keymap-dialog').addEventListener('close',()=>{stopCapture(false);el('open-keymap').focus()})"),
    'keymap close must retire capture before restoring opener focus'
  );
  let captureClassRemoved=0, capturePressed='', captureText='';
  const captureButton={
    classList:{remove:name=>{assert.equal(name,'capture-active');captureClassRemoved+=1;}},
    setAttribute:(name,value)=>{if(name==='aria-pressed')capturePressed=value;},
    set textContent(value){captureText=value;},
    get textContent(){return captureText;},
  };
  shell.capture={button:captureButton};
  vm.runInContext(html.split('\n').find(line=>line.startsWith('function stopCapture(')),shell);
  shell.stopCapture(false);
  assert.equal(shell.capture,null,'closing capture must clear the hidden capture authority');
  assert.equal(captureClassRemoved,1);
  assert.equal(capturePressed,'false');
  assert.equal(captureText,'Нова комбінація');

  const sound=fs.readFileSync('web/stage1_release_bootstrap.js','utf8');
  assert(!sound.includes('sound-preview'));
  assert(!sound.includes('preview_sound'));
  console.log('Owner gameplay keyboard and feedback: PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
