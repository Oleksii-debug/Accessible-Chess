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
  // A user is allowed to save a printable global binding, but editable controls
  // must not turn ordinary text entry into a destructive global command.
  shell.keymap.find(row => row.id === 'file.new').binding = 'E';
  rows.find(row => row.id === 'file.new').binding = 'E';
  calls.length = 0;
  await listener(event('e', {}));
  assert.equal(calls.length, 0, 'plain printable file.new remap must not consume editable typing');
  // Non-text command keys remain usable from the same editable surface.
  shell.keymap.find(row => row.id === 'file.new').binding = 'F6';
  rows.find(row => row.id === 'file.new').binding = 'F6';
  calls.length = 0;
  await listener(event('F6', {}));
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
  response.announceMoveErrors=true;
  await shell.apiAction('make_move','nf9');
  assert.equal(spoken.length,1);
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
  const sound=fs.readFileSync('web/stage1_release_bootstrap.js','utf8');
  assert(!sound.includes('sound-preview'));
  assert(!sound.includes('preview_sound'));
  console.log('Owner gameplay keyboard and feedback: PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
