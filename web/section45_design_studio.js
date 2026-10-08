/* Accessible Chess Section 45: one bounded presentation profile contract.
 * The existing board handlers remain the sole board mutation authority.
 * Browser/Web profiles are LOCAL ONLY; file export/import is explicit sync.
 */
(function () {
"use strict";
const VERSION = 1, STORE_KEY = "accessible-chess.design-profiles.v1";
const defaults = Object.freeze({
  theme:"system",board_theme:"classic",piece_theme:"unicode",font_percent:100,
  board_scale:100,density:"comfortable",layout:"auto",coordinates:"edges",
  orientation:"white",highlight:true,animations:false,sound:true
});
const presets = Object.freeze({
  "Classic": {...defaults},
  "Tournament": {...defaults,board_theme:"tournament_blue",density:"compact",coordinates:"every_square"},
  "Coach": {...defaults,font_percent:125,board_scale:125},
  "Classroom Presentation": {...defaults,font_percent:150,board_scale:150,coordinates:"every_square"},
  "Low Vision": {...defaults,font_percent:175,board_scale:175,board_theme:"high_contrast"},
  "High Contrast": {...defaults,theme:"contrast",board_theme:"high_contrast",piece_theme:"letters",font_percent:125}
});
const choices = {
  theme:["system","light","dark","contrast"],
  board_theme:["classic","high_contrast","blue","classic_wood","modern_graphite","tournament_blue","light_minimal"],
  piece_theme:["unicode","letters","rhosgfx"],
  font_percent:[75,100,125,150,175,200],
  board_scale:[75,100,125,150,175,200],
  density:["comfortable","compact"],layout:["auto","single"],
  coordinates:["off","edges","every_square"],orientation:["white","black"],
  highlight:[true,false],animations:[false,true],sound:[true,false]
};
const labels = {
 theme:["Тема інтерфейсу","Interface theme"],board_theme:["Кольори дошки","Board colours"],
 piece_theme:["Фігури","Pieces"],font_percent:["Розмір тексту","Text size"],
 board_scale:["Розмір дошки","Board size"],density:["Щільність","Density"],
 layout:["Компонування","Layout"],coordinates:["Координати","Coordinates"],
 orientation:["Орієнтація дошки","Board orientation"],highlight:["Підсвічування","Highlighting"],
 animations:["Анімація","Animation"],sound:["Звук","Sound"]
};
const blankStore = () => ({version:VERSION,selected:"Classic",profiles:{}});
const el = id => document.getElementById(id);
const en = () => document.documentElement.lang === "en";
const say = (uk, english) => en() ? english : uk;
const own = (v, k) => Object.prototype.hasOwnProperty.call(v,k);
const plain = v => v !== null && typeof v === "object" && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;
const identicalKeys = (value,keys) => Object.keys(value).length === keys.length && keys.every(k=>own(value,k));
const validName = name => typeof name === "string" && name.length > 0 && name.length <= 48
  && name.trim() === name && !/[\\/\u0000-\u001f\u007f<>:"|?*]/.test(name)
  && ![".","..","__proto__","constructor","prototype"].includes(name)
  && !Object.keys(presets).some(n=>n.toLowerCase()===name.toLowerCase());
function validPrefs(p) {
  if (!plain(p) || !identicalKeys(p,Object.keys(defaults))) return false;
  return Object.keys(choices).every(k =>
    choices[k].some(v=>v === p[k] && typeof v === typeof p[k]));
}
function validStore(s) {
  if (!plain(s) || !identicalKeys(s,["version","selected","profiles"]) ||
      s.version !== 1 || !plain(s.profiles)) return false;
  const names=Object.keys(s.profiles);
  if (names.length>16 || new Set(names.map(n=>n.toLowerCase())).size !== names.length) return false;
  if (!names.every(n=>validName(n)&&validPrefs(s.profiles[n]))) return false;
  return typeof s.selected === "string" && (own(presets,s.selected) || own(s.profiles,s.selected));
}
// Native Settings uses duplicate-key rejecting JSON. Web imports must share
// the same rejection policy, not JSON.parse's silent last-key-wins behavior.
function uniqueObjectKeys(raw) {
  const frames=[];
  for(let i=0;i<raw.length;i++){
    const ch=raw[i];
    if(ch==="{"){frames.push(new Set());continue;}
    if(ch==="["){frames.push(null);continue;}
    if(ch==="}"||ch==="]"){if(!frames.length)return false;frames.pop();continue;}
    if(ch!=='"')continue;
    let end=i+1;
    while(end<raw.length){
      if(raw[end]==="\\"){end+=2;continue;}
      if(raw[end]==='"')break;
      end++;
    }
    if(end>=raw.length)return false;
    let after=end+1;
    while(after<raw.length&&/\s/.test(raw[after]))after++;
    if(raw[after]===":"){
      const current=frames[frames.length-1];
      if(!(current instanceof Set))return false;
      let key;
      try{key=JSON.parse(raw.slice(i,end+1));}catch(_){return false;}
      if(current.has(key))return false;
      current.add(key);
    }
    i=end;
  }
  return frames.length===0;
}
function safeParse(raw) {
  if (typeof raw !== "string" || raw.length > 16384) return null;
  try {
    if(!uniqueObjectKeys(raw))return null;
    const parsed=JSON.parse(raw);
    return validStore(parsed)?parsed:null;
  } catch (_) { return null; }
}
function currentPrefs() {
  const name=store.selected;
  return {...(own(presets,name)?presets[name]:store.profiles[name])};
}
function nativeApi() {
  const bridge=window.pywebview && window.pywebview.api;
  return bridge && typeof bridge.get_design_studio_state==="function" &&
    typeof bridge.save_design_studio_state==="function" ? bridge : null;
}
let store=blankStore(), revision=null, localBaseline=null, localCorrupt=false, active={...defaults}, dirty=false, working={...defaults};
function status(uk,english,error) {
  const n=el("ac45-status");
  if(n){n.textContent=say(uk,english);n.dataset.error=error?"true":"false";}
}
function localRead() {
  try {
    localBaseline=window.localStorage.getItem(STORE_KEY);
    const parsed=localBaseline===null?null:safeParse(localBaseline);
    localCorrupt=localBaseline!==null&&!parsed;
    return parsed;
  } catch (_) { localBaseline=null;return null; }
}
function localWrite(value) {
  const data=JSON.stringify(value);
  if (data.length>16384) return false;
  try {
    // Web has no server-side profile authority: refuse a stale local tab
    // instead of silently overwriting another tab's changed profile.
    if(localCorrupt||window.localStorage.getItem(STORE_KEY)!==localBaseline)return false;
    window.localStorage.setItem(STORE_KEY,data);
    localBaseline=data;
    return true;
  } catch (_) { return false; }
}
function add(tag,parent,id,txt) {
  const n=document.createElement(tag);
  if(id)n.id=id;
  if(typeof txt==="string")n.textContent=txt;
  parent.appendChild(n);
  return n;
}
function button(parent,id,uk,english,fn) {
  const n=add("button",parent,id,say(uk,english));n.type="button";n.addEventListener("click",fn);return n;
}
function choicesLabel(key,raw) {
  if (typeof raw==="boolean") return raw?say("Так","Yes"):say("Ні","No");
  if(typeof raw==="number") return String(raw)+"%";
  return String(raw).replace(/_/g," ");
}
function refreshProfileOptions() {
  const n=el("ac45-profile"),selection=store.selected;
  n.textContent="";
  for(const key of [...Object.keys(presets),...Object.keys(store.profiles)]) {
    const item=add("option",n,null,key);item.value=key;
  }
  n.value=selection;
}
function refreshControls() {
  for(const key of Object.keys(defaults)){
    const n=el("ac45-"+key.replace(/_/g,"-"));
    if(n)n.value=String(working[key]);
  }
  dirty=false;
}
function preview() {
  const panel=el("ac45-preview");
  if(!panel)return;
  panel.dataset.theme=working.theme;
  panel.dataset.board=working.board_theme;
  panel.dataset.pieces=working.piece_theme;
  panel.dataset.orientation=working.orientation;
  panel.dataset.highlight=working.highlight?"true":"false";
  panel.style.fontSize=String(working.font_percent)+"%";
  panel.style.lineHeight=working.density==="compact"?"1.2":"1.65";
  panel.textContent="";
  // This is fixed, deliberately non-interactive *decorative* sample data.
  // No FEN, move legality, GameTree or second chess position authority.
  // The authentic 64-cell board and its NVDA labels remain untouched.
  add("p",panel,null,say("Приклад оформлення (без зміни партії)",
    "Appearance sample (game unchanged)"));
  const sample=add("div",panel,"ac45-preview-board");
  sample.className="ac45-preview-board";
  sample.setAttribute("aria-hidden","true");
  sample.dataset.theme=working.board_theme;
  sample.dataset.pieces=working.piece_theme;
  const unicode={K:"♔",Q:"♕",R:"♖",B:"♗",N:"♘",P:"♙",
                 k:"♚",q:"♛",r:"♜",b:"♝",n:"♞",p:"♟"};
  const fixed={a8:"r",b8:"n",c8:"b",d8:"q",e8:"k",f8:"b",g8:"n",h8:"r",
               a7:"p",b7:"p",c7:"p",d7:"p",e7:"p",f7:"p",g7:"p",h7:"p",
               a2:"P",b2:"P",c2:"P",d2:"P",e2:"P",f2:"P",g2:"P",h2:"P",
               a1:"R",b1:"N",c1:"B",d1:"Q",e1:"K",f1:"B",g1:"N",h1:"R"};
  const ranks=working.orientation==="black"?[1,2,3,4,5,6,7,8]:[8,7,6,5,4,3,2,1];
  const files=working.orientation==="black"?"hgfedcba":"abcdefgh";
  for(const rank of ranks)for(const file of files){
    const square=file+String(rank);
    const cell=add("span",sample,null);
    cell.className="ac45-sample-square";
    cell.dataset.light=(("abcdefgh".indexOf(file)+rank)%2===0)?"true":"false";
    const piece=fixed[square];
    if(!piece)continue;
    if(working.piece_theme==="rhosgfx"){
      const img=add("img",cell,null);
      const code=(piece===piece.toUpperCase()?"w":"b")+piece.toUpperCase()+".svg";
      img.src="assets/pieces/rhosgfx/"+code;
      img.alt="";
      img.setAttribute("aria-hidden","true");
      img.addEventListener("error",()=>{img.remove();cell.textContent=unicode[piece]||piece;});
    }else cell.textContent=working.piece_theme==="letters"?piece:unicode[piece];
  }
  const note=add("p",panel,null,say(
    "Поля та фігури тут лише для перегляду; шахові ходи недоступні.",
    "These sample squares and pieces are decorative; no moves can be made."));
  note.className="ac45-preview-note";
  status("Попередній перегляд не змінює позицію або партію.",
    "Preview does not change the position or game.");
}
function presentationApply(p, emitBoardActions = true) {
  const root=document.documentElement;
  root.dataset.ac45Font=String(p.font_percent);
  root.style.setProperty("--ac45-font-scale",String(p.font_percent/100));
  root.dataset.ac45Density=p.density;
  root.dataset.ac45Highlight=p.highlight?"true":"false";
  const selected=el("ac41-theme");
  if(selected){selected.value=p.theme;selected.dispatchEvent(new Event("change",{bubbles:true}));}
  else root.dataset.acUiTheme=p.theme;
  const targets=[
    ["board-theme",p.board_theme],["piece-theme",p.piece_theme],
    ["board-orientation",p.orientation],["board-coordinates",p.coordinates],
    ["board-scale",p.board_scale],["board-show-last",p.highlight],
    ["board-animations",p.animations],["ac43-density",p.density],
    ["ac43-layout",p.layout]
  ];
  if(emitBoardActions)targets.forEach(([id,value])=>{
    const node=el(id);
    if(!node)return;
    if(node.type==="checkbox")node.checked=value;
    else node.value=String(value);
    node.dispatchEvent(new Event("change",{bubbles:true}));
  });
  // Sound is a profile preference, but its canonical per-event runtime
  // is NOT replaced. No synthetic audio toggle is sent to the chess core.
  root.dataset.ac45Sound=p.sound?"on":"off";
  const webBoard=el("board-grid");
  if(webBoard&&!el("board-scale")){
    webBoard.style.maxWidth="min(100%,"+String(42*p.board_scale/100)+"rem)";
  }
}
function stateCandidate(nextPrefs,name) {
  const next=JSON.parse(JSON.stringify(store));
  const base=own(presets,name)?presets[name]:next.profiles[name];
  if(JSON.stringify(base)!==JSON.stringify(nextPrefs)){
    if(own(presets,name)) {
      let custom="Personalized",i=2;
      while(own(next.profiles,custom))custom="Personalized "+String(i++);
      if(Object.keys(next.profiles).length>=16)throw new Error("profile limit");
      next.profiles[custom]={...nextPrefs};next.selected=custom;
    } else next.profiles[name]={...nextPrefs};
  } else next.selected=name;
  return next;
}
async function persist(next) {
  if(!validStore(next))throw new Error("invalid profile");
  const bridge=nativeApi();
  if(bridge){
    if(typeof revision!=="string")throw new Error("native state not loaded");
    const response=await bridge.save_design_studio_state(next,revision);
    if(!response||response.ok!==true||!validStore(response.store)){
      throw new Error(response&&response.reason==="stale_revision"?"stale revision":"save rejected");
    }
    revision=response.revision;store=response.store;
  }else{
    if(!localWrite(next))throw new Error("browser storage unavailable");
    store=next;
  }
  refreshProfileOptions();
}
async function apply() {
  if(!validPrefs(working)){status("Некоректні налаштування.","Invalid preferences.",true);return;}
  try{
    const next=stateCandidate(working,el("ac45-profile").value);
    await persist(next);
    active={...working};presentationApply(active);
    refreshControls();
    const bridge=nativeApi();
    if(bridge&&typeof bridge.set_sound_enabled==="function"){
      try{
        const sound=await bridge.set_sound_enabled(active.sound);
        if(!sound||sound.ok!==true){
          status("Оформлення збережено, але звук не змінився. Перевірте його окремо.",
            "Design saved, but sound was not changed. Check sound separately.",true);
          return;
        }
      }catch(_){
        status("Оформлення збережено, але звук недоступний.",
          "Design saved, but sound is unavailable.",true);
        return;
      }
    }
    status("Профіль застосовано та збережено.","Profile applied and saved.");
  }catch(err){status("Не збережено: конфлікт або недоступне сховище. Відкрийте налаштування знову.",
    "Not saved: conflict or storage unavailable. Reopen preferences.",true);}
}
async function copyProfile() {
  const name=el("ac45-name").value;
  if(!validName(name)||own(store.profiles,name)||Object.keys(store.profiles).length>=16){
    status("Назва недопустима, зайнята або досягнуто ліміту.","Invalid or duplicate name, or profile limit reached.",true);
    return;
  }
  try{
    const next=JSON.parse(JSON.stringify(store));
    next.profiles[name]={...working};next.selected=name;
    await persist(next);
    active={...working};presentationApply(active);refreshControls();
    status("Персональний профіль створено.","Custom profile created.");
  }catch(_){status("Профіль не збережено.","Profile not saved.",true);}
}
function exportProfile(){
  if(!validStore(store)){status("Некоректний профіль.","Invalid profile.",true);return;}
  const raw=JSON.stringify(store);
  if(raw.length>16384)return;
  const blob=new Blob([raw],{type:"application/json"});
  const url=URL.createObjectURL(blob),a=document.createElement("a");
  a.href=url;a.download="accessible-chess-design-profiles.json";a.click();
  URL.revokeObjectURL(url);
  status("Експорт без приватних шляхів і шахових даних.","Export contains no private paths or chess data.");
}
async function importProfile(file) {
  if(!file || file.size>16384){status("Файл завеликий.","File too large.",true);return;}
  try{
    const raw=await file.text(),candidate=safeParse(raw);
    if(!candidate)throw new Error("invalid");
    if(!window.confirm(say("Замінити профілі оформлення?","Replace design profiles?")))return;
    await persist(candidate);
    working=currentPrefs();refreshControls();active={...working};
    presentationApply(active);
    status("Імпортовано й застосовано.","Imported and applied.");
  }catch(_){status("Не вдалося імпортувати профіль.","Could not import profile.",true);}
}
async function hydrate(){
  const bridge=nativeApi();
  if(bridge){
    try {
      const response=await bridge.get_design_studio_state();
      if(!response||!response.ok||!validStore(response.store))throw new Error("unsafe native state");
      store=response.store;revision=response.revision;
      status("Профілі завантажено із захищеного сховища Windows.",
        "Profiles loaded from protected Windows storage.");
    }catch(_){
      status("Налаштування Windows недоступні. Зміни не зберігатимуться.",
        "Windows preferences unavailable. Changes will not be saved.",true);
      el("ac45-apply").disabled=true;el("ac45-copy").disabled=true;
      return;
    }
  }else{
    store=localRead()||blankStore();
    if(localCorrupt){
      status("Пошкоджені вебпрофілі збережені без змін. Щоб відновити типові значення, натисніть Скинути, тоді Застосувати.",
        "Corrupt Web profiles preserved. To replace with defaults choose Reset and then Apply.",true);
    }else status("Вебпрофілі локальні. Передача між пристроями — лише через експорт/імпорт.",
      "Web profiles are local. Sync between devices requires explicit export/import.");
  }
  active=currentPrefs();working={...active};
  refreshProfileOptions();refreshControls();presentationApply(active,false);
}
function init(){
  if(el("ac45-studio"))return;
  const host=el("h-settings")?.closest("section")||el("ac41-theme")?.parentElement||
    document.querySelector("header")||document.body;
  const section=add("section",host,"ac45-studio");
  section.setAttribute("aria-labelledby","ac45-title");
  add("h3",section,"ac45-title",say("Студія оформлення","Design studio"));
  const toggle=button(section,"ac45-toggle","Відкрити студію","Open design studio",()=>{
    const hidden=body.hidden;body.hidden=!hidden;
    toggle.setAttribute("aria-expanded",hidden?"true":"false");
    toggle.textContent=hidden?say("Закрити студію","Close design studio"):
      say("Відкрити студію","Open design studio");
    if(hidden)el("ac45-profile").focus();
  });
  toggle.setAttribute("aria-expanded","false");toggle.setAttribute("aria-controls","ac45-panel");
  const body=add("div",section,"ac45-panel");body.hidden=true;
  const group=add("fieldset",body,null);
  add("legend",group,null,say("Профіль і параметри","Profile and preferences"));
  const profileLabel=add("label",group,null,say("Профіль","Profile"));
  profileLabel.htmlFor="ac45-profile";
  const profile=add("select",group,"ac45-profile");
  profile.addEventListener("change",()=>{
    const name=profile.value;
    working={...(own(presets,name)?presets[name]:store.profiles[name])};
    refreshControls();preview();
  });
  for(const key of Object.keys(defaults)){
    const row=add("div",group,null);row.className="ac45-control-row";
    const id="ac45-"+key.replace(/_/g,"-");
    const label=add("label",row,null,say(...labels[key]));label.htmlFor=id;
    const select=add("select",row,id);
    for(const value of choices[key]){
      const option=add("option",select,null,choicesLabel(key,value));
      option.value=String(value);
    }
    select.addEventListener("change",()=>{
      const raw=select.value;
      working[key]=typeof defaults[key]==="number"?Number(raw):
        typeof defaults[key]==="boolean"?raw==="true":raw;
      dirty=true;
    });
  }
  const previewArea=add("div",body,"ac45-preview");previewArea.setAttribute("role","note");
  const actions=add("div",body,null);actions.className="ac45-actions";
  button(actions,"ac45-preview-button","Попередній перегляд","Preview",preview);
  button(actions,"ac45-apply","Застосувати","Apply",()=>void apply());
  button(actions,"ac45-cancel","Скасувати","Cancel",()=>{
    el("ac45-profile").value=store.selected;
    working={...active};refreshControls();preview();
    status("Незбережені зміни скасовано.","Uncommitted changes cancelled.");
  });
  button(actions,"ac45-reset","Скинути","Reset",()=>{
    // Reset is an explicit user choice to replace an unreadable Web blob.
    // Preview and Cancel alone never authorize destruction of old bytes.
    localCorrupt=false;
    working={...defaults};refreshControls();preview();
    status("Показано типові значення. Для збереження виберіть Застосувати.",
      "Defaults previewed. Select Apply to save.");
  });
  const nameLabel=add("label",body,null,say("Назва нового профілю","New profile name"));
  nameLabel.htmlFor="ac45-name";
  const name=add("input",body,"ac45-name");name.type="text";name.maxLength=48;
  name.autocomplete="off";name.spellcheck=false;
  button(body,"ac45-copy","Зберегти копію","Save copy",()=>void copyProfile());
  button(body,"ac45-export","Експорт профілів","Export profiles",exportProfile);
  const importLabel=add("label",body,null,say("Імпорт профілів","Import profiles"));
  importLabel.htmlFor="ac45-import";
  const input=add("input",body,"ac45-import");input.type="file";input.accept=".json,application/json";
  input.addEventListener("change",()=>{void importProfile(input.files&&input.files[0]);input.value="";});
  const live=add("p",section,"ac45-status");
  live.setAttribute("role","status");live.setAttribute("aria-live","polite");
  refreshProfileOptions();refreshControls();preview();
  void hydrate();
  window.addEventListener("storage",event=>{
    if(event && event.key===STORE_KEY && event.newValue!==localBaseline)
      status("Профіль змінено в іншій вкладці. Повторно відкрийте сторінку перед збереженням.",
        "Profiles changed in another tab. Reload before saving.",true);
  });
  window.addEventListener("pywebviewready",()=>void hydrate());
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);
else init();
})();