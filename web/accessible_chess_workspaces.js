(() => {
'use strict';

const SCHEMA_VERSION = 1;
const WORKSPACES = [
  ['chess','Chess','Шахи'],
  ['library','Library','Бібліотека'],
  ['books','Books','Книги'],
  ['training','Training','Тренування'],
  ['teacher','Teacher','Викладач'],
  ['student','Student','Учень'],
  ['media','Media','Медіа'],
];
const CLASSIFIERS = [
  ['chess',['h-game-info','h-moves','h-white','h-black','h-status','h-last','h-input','h-engine','h-board','h-actions']],
  ['library',['h-library','library-workspace','v2-library-workspace']],
  ['books',['h-books','book-reader','v2-book-workspace']],
  ['training',['h-training','training-workspace','v2-training-workspace']],
  ['teacher',['h-teacher','teacher-workspace','v2-teacher-workspace','h-classroom']],
  ['student',['h-student','student-workspace','education-workspace']],
  ['media',['h-media','media-workspace','recorded-media-player','youtube-player']],
];
const el = id => document.getElementById(id);
const lang = () => document.documentElement.lang === 'en' ? 'en' : 'uk';
const label = pair => lang() === 'en' ? pair[1] : pair[2];

function api(){
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}
function status(text){
  const node=el('ac-workspace-status');
  if(node) node.textContent=String(text||'');
}
function safeWorkspace(value){
  return WORKSPACES.some(item=>item[0]===value) ? value : 'chess';
}
function sectionHeadingId(section){
  const heading=section.querySelector('h1,h2,h3');
  return heading && heading.id ? heading.id : '';
}
function classifySection(section){
  const ids=new Set([section.id,sectionHeadingId(section)].filter(Boolean));
  for(const [workspace,markers] of CLASSIFIERS){
    if(markers.some(marker=>ids.has(marker))) return workspace;
  }
  return section.dataset.acWorkspace || 'chess';
}
function panelId(section,index){
  return section.id || sectionHeadingId(section) || ('panel-'+String(index+1));
}
function decoratePanels(){
  const main=el('main-content');
  if(!main) return;
  const sections=[...main.querySelectorAll(':scope > section')];
  sections.forEach((section,index)=>{
    section.classList.add('ac-panel');
    section.dataset.acWorkspace=classifySection(section);
    section.dataset.acPanelId=panelId(section,index);
    if(section.querySelector('.ac-panel-toolbar')) return;
    const heading=section.querySelector(':scope > h2,:scope > h3');
    if(!heading) return;
    const toolbar=document.createElement('div');
    toolbar.className='ac-panel-toolbar';
    const toggle=document.createElement('button');
    toggle.type='button';
    toggle.className='ac-panel-toggle';
    toggle.setAttribute('aria-expanded','true');
    toggle.textContent=lang()==='en'?'Collapse':'Згорнути';
    toggle.addEventListener('click',()=>{
      const collapsed=section.dataset.acCollapsed!=='true';
      setPanelCollapsed(section,collapsed,true);
    });
    toolbar.appendChild(toggle);
    heading.insertAdjacentElement('afterend',toolbar);
  });
}
function setPanelCollapsed(section,collapsed,persist){
  section.dataset.acCollapsed=collapsed?'true':'false';
  const button=section.querySelector('.ac-panel-toggle');
  if(button){
    button.setAttribute('aria-expanded',collapsed?'false':'true');
    button.textContent=collapsed?(lang()==='en'?'Expand':'Розгорнути'):(lang()==='en'?'Collapse':'Згорнути');
  }
  if(persist) persistLayout();
}
function currentPanels(workspace){
  return [...document.querySelectorAll('.ac-panel')]
    .filter(node=>node.dataset.acWorkspace===workspace);
}
function captureLayout(workspace){
  const panels=currentPanels(workspace);
  return {
    workspace,
    panel_order:panels.map(node=>node.dataset.acPanelId),
    collapsed:panels.filter(node=>node.dataset.acCollapsed==='true').map(node=>node.dataset.acPanelId),
    primary_percent:Number(document.documentElement.dataset.acPrimaryPercent||62),
  };
}
async function persistLayout(){
  const a=api();
  if(!(a && typeof a.design_update_layout==='function')) return;
  const workspace=safeWorkspace(document.documentElement.dataset.acWorkspace||'chess');
  const layout=captureLayout(workspace);
  try{
    const result=await a.design_update_layout(
      layout.workspace,layout.panel_order,layout.collapsed,layout.primary_percent
    );
    if(result && result.ok===false) status(result.message||'');
  }catch(_error){
    status(lang()==='en'?'Layout could not be saved.':'Не вдалося зберегти розкладку.');
  }
}
function applyWorkspaceLayout(snapshot,workspace){
  const layouts=snapshot && snapshot.preferences && Array.isArray(snapshot.preferences.layouts)
    ? snapshot.preferences.layouts : [];
  const layout=layouts.find(item=>item && item.workspace===workspace);
  if(!layout) return;
  const main=el('main-content');
  const panels=currentPanels(workspace);
  const byId=new Map(panels.map(node=>[node.dataset.acPanelId,node]));
  if(Array.isArray(layout.panel_order)){
    layout.panel_order.forEach(id=>{const node=byId.get(id);if(node)main.appendChild(node)});
  }
  const collapsed=new Set(Array.isArray(layout.collapsed)?layout.collapsed:[]);
  panels.forEach(node=>setPanelCollapsed(node,collapsed.has(node.dataset.acPanelId),false));
  const primary=Number(layout.primary_percent);
  if(Number.isInteger(primary)&&primary>=35&&primary<=80){
    document.documentElement.dataset.acPrimaryPercent=String(primary);
    document.documentElement.style.setProperty('--ac-primary',String(primary)+'%');
  }
}
function showWorkspace(workspace,focus=true){
  const selected=safeWorkspace(workspace);
  document.documentElement.dataset.acWorkspace=selected;
  document.querySelectorAll('.ac-panel').forEach(node=>{
    node.hidden=node.dataset.acWorkspace!==selected;
  });
  document.querySelectorAll('#ac-workspace-toolbar button[data-workspace]').forEach(button=>{
    const active=button.dataset.workspace===selected;
    if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  });
  const snapshot=window.__accessibleChessDesignSnapshot || null;
  applyWorkspaceLayout(snapshot,selected);
  const panels=currentPanels(selected).filter(node=>!node.hidden);
  if(panels.length)panels[0].dataset.acPrimary='true';
  if(focus&&panels.length){
    const heading=panels[0].querySelector('h1,h2,h3');
    if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true})}
  }
  status((lang()==='en'?'Workspace: ':'Робоча область: ')+label(WORKSPACES.find(item=>item[0]===selected)));
}
function buildToolbar(){
  if(el('ac-workspace-toolbar'))return;
  const main=el('main-content'); if(!main)return;
  const toolbar=document.createElement('nav');
  toolbar.id='ac-workspace-toolbar';
  toolbar.setAttribute('aria-label',lang()==='en'?'Workspaces':'Робочі області');
  WORKSPACES.forEach(item=>{
    const button=document.createElement('button');
    button.type='button';button.dataset.workspace=item[0];button.textContent=label(item);
    button.addEventListener('click',()=>showWorkspace(item[0],true));
    toolbar.appendChild(button);
  });
  const design=document.createElement('button');
  design.type='button';design.id='ac-open-design';design.textContent=lang()==='en'?'Appearance':'Вигляд';
  design.addEventListener('click',openDesignDialog);
  toolbar.appendChild(design);
  const statusNode=document.createElement('p');
  statusNode.id='ac-workspace-status';statusNode.setAttribute('aria-live','polite');
  main.insertAdjacentElement('afterbegin',statusNode);
  main.insertAdjacentElement('afterbegin',toolbar);
}
function designDialog(){
  if(el('ac-design-dialog'))return el('ac-design-dialog');
  const dialog=document.createElement('dialog');dialog.id='ac-design-dialog';
  dialog.setAttribute('aria-labelledby','ac-design-title');
  dialog.innerHTML=`
    <h2 id="ac-design-title">${lang()==='en'?'Appearance and interface':'Вигляд і інтерфейс'}</h2>
    <div class="ac-design-grid">
      <label>${lang()==='en'?'Profile':'Профіль'}<select id="ac-design-profile">
        <option value="classic">Classic</option><option value="tournament">Tournament</option>
        <option value="coach">Coach</option><option value="classroom_presentation">Classroom Presentation</option>
        <option value="low_vision">Low Vision</option><option value="high_contrast">High Contrast</option>
      </select></label>
      <label>${lang()==='en'?'Theme':'Тема'}<select id="ac-design-theme">
        <option value="system">System</option><option value="light">Light</option>
        <option value="dark">Dark</option><option value="high_contrast">High Contrast</option>
      </select></label>
      <label>${lang()==='en'?'Text size':'Розмір тексту'}<input id="ac-design-text" type="number" min="75" max="250" step="5"></label>
      <label>${lang()==='en'?'Interface zoom':'Масштаб інтерфейсу'}<input id="ac-design-zoom" type="number" min="75" max="250" step="5"></label>
      <label>${lang()==='en'?'Density':'Щільність'}<select id="ac-design-density">
        <option value="comfortable">Comfortable</option><option value="compact">Compact</option>
        <option value="presentation">Presentation</option>
      </select></label>
    </div>
    <p id="ac-design-preview-status" role="status"></p>
    <div class="row">
      <button type="button" id="ac-design-preview">${lang()==='en'?'Preview':'Попередній перегляд'}</button>
      <button type="button" id="ac-design-apply">${lang()==='en'?'Apply':'Застосувати'}</button>
      <button type="button" id="ac-design-reset">${lang()==='en'?'Reset':'Скинути'}</button>
      <button type="button" id="ac-design-cancel">${lang()==='en'?'Cancel':'Скасувати'}</button>
    </div>`;
  document.body.appendChild(dialog);
  el('ac-design-profile').addEventListener('change',previewPreset);
  el('ac-design-preview').addEventListener('click',previewCustom);
  el('ac-design-apply').addEventListener('click',applyDesign);
  el('ac-design-reset').addEventListener('click',resetDesign);
  el('ac-design-cancel').addEventListener('click',cancelDesign);
  return dialog;
}
function applyDesignValues(prefs){
  if(!prefs)return;
  const root=document.documentElement;
  root.dataset.acTheme=String(prefs.theme||'system');
  root.dataset.acDensity=String(prefs.density||'comfortable');
  root.style.setProperty('--ac-font-scale',String(Number(prefs.text_scale_percent||100)/100));
  root.style.setProperty('--ac-ui-zoom',String(Number(prefs.app_zoom_percent||100)/100));
  root.dataset.acFocusRing=Number(prefs.highlight_percent||100)>=140?'strong':'normal';
  const theme=String(prefs.theme||'system');
  root.style.colorScheme=theme==='dark'?'dark':theme==='light'?'light':'';
}
function fillDesign(snapshot){
  window.__accessibleChessDesignSnapshot=snapshot||null;
  const prefs=snapshot&&snapshot.preferences||{};
  const set=(id,value)=>{const node=el(id);if(node&&value!=null)node.value=String(value)};
  set('ac-design-theme',prefs.theme||'system');set('ac-design-density',prefs.density||'comfortable');
  set('ac-design-text',prefs.text_scale_percent||100);set('ac-design-zoom',prefs.app_zoom_percent||100);
  applyDesignValues(prefs);
}
async function refreshDesign(){
  const a=api();
  if(a&&typeof a.design_snapshot==='function'){
    try{const snapshot=await a.design_snapshot();fillDesign(snapshot);return snapshot}catch(_error){}
  }
  const fallback={schema_version:SCHEMA_VERSION,preferences:{theme:'system',density:'comfortable',text_scale_percent:100,app_zoom_percent:100,highlight_percent:100,layouts:[]}};
  fillDesign(fallback);return fallback;
}
async function previewPreset(){
  const a=api(),id=el('ac-design-profile').value;
  if(a&&typeof a.design_preview_preset==='function'){
    const r=await a.design_preview_preset(id);if(r&&r.preferences){fillDesign(r);return}
  }
}
async function previewCustom(){
  const a=api();if(!(a&&typeof a.design_preview_fields==='function'))return;
  const r=await a.design_preview_fields(
    el('ac-design-theme').value,el('ac-design-density').value,
    Number(el('ac-design-text').value),Number(el('ac-design-zoom').value)
  );
  if(r&&r.preferences){fillDesign(r);el('ac-design-preview-status').textContent=lang()==='en'?'Preview only; not saved.':'Лише перегляд; ще не збережено.'}
}
async function applyDesign(){
  const a=api();if(!(a&&typeof a.design_apply==='function'))return;
  const r=await a.design_apply();if(r&&r.preferences){fillDesign(r);el('ac-design-preview-status').textContent=lang()==='en'?'Appearance saved.':'Вигляд збережено.'}
}
async function resetDesign(){
  const a=api();if(a&&typeof a.design_reset==='function'){const r=await a.design_reset();if(r&&r.preferences)fillDesign(r)}
}
async function cancelDesign(){
  const a=api();if(a&&typeof a.design_cancel==='function'){const r=await a.design_cancel();if(r&&r.preferences)fillDesign(r)}
  const d=el('ac-design-dialog');if(d)d.close();const opener=el('ac-open-design');if(opener)opener.focus();
}
async function openDesignDialog(){
  const d=designDialog();await refreshDesign();d.showModal();el('ac-design-profile').focus();
}
function install(){
  decoratePanels();buildToolbar();designDialog();refreshDesign().then(()=>showWorkspace('chess',false));
  const main=el('main-content');
  if(main){
    const observer=new MutationObserver(()=>{decoratePanels();showWorkspace(document.documentElement.dataset.acWorkspace||'chess',false)});
    observer.observe(main,{childList:true,subtree:false});
  }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
window.AccessibleChessWorkspaces=Object.freeze({showWorkspace,captureLayout,refreshDesign});
})();