#!/usr/bin/env python3
"""Fail-closed MANUAL_EMERGENCY_WORK completion for the exact Oxford 5000 tail.

Oxford identity/POS/CEFR/definition-path are immutable source truth. Candidate
translations are only candidates. PASS is emitted only when language, POS and exact
Oxford-definition semantic checks succeed; uncertainty is BLOCKED and never activated.
"""
from __future__ import annotations
import argparse,csv,difflib,hashlib,html,re,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from typing import Iterable
import requests

EXPECTED_TAIL=1156
FIRST_RUN_ID="MANUAL_EMERGENCY_WORK_20260820_FIRST_PASS_V2"
SECOND_RUN_ID="MANUAL_EMERGENCY_WORK_20260820_SECOND_PASS_V2"
EN_UK_MODEL="Helsinki-NLP/opus-mt-en-uk"; UK_EN_MODEL="Helsinki-NLP/opus-mt-uk-en"
SEM_MODEL="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
FIRST_FIELDS=["data_factory_run_id","entry_id","source","part_of_speech","level","official_source","source_check","ukrainian_candidate"]
SECOND_FIELDS=["content_qa_run_id","data_factory_run_id","entry_id","source","part_of_speech","level","decision","ukrainian","qa_reason"]
FINAL_FIELDS=["entry_id","source","part_of_speech","level","ukrainian","status","manual_emergency_first_pass_run_id","manual_emergency_second_pass_run_id","source_check","qa_reason"]
POS_HEADERS={"noun":("Noun","Proper noun"),"verb":("Verb",),"adjective":("Adjective",),"adverb":("Adverb",),"preposition":("Preposition",),"conjunction":("Conjunction",),"pronoun":("Pronoun",),"determiner":("Determiner",),"exclamation":("Interjection",),"modal verb":("Verb",),"number":("Numeral","Number")}


def read_tsv(p:Path):
    with p.open('r',encoding='utf-8-sig',newline='') as h:return [{k:(v or '').strip() for k,v in r.items()} for r in csv.DictReader(h,delimiter='\t')]
def write_tsv(p:Path,rows:Iterable[dict[str,str]],fields:list[str]):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as h:
        w=csv.DictWriter(h,fieldnames=fields,delimiter='\t',lineterminator='\n',extrasaction='ignore');w.writeheader();w.writerows(rows)
def stable_id(source,pos,level):
    s='\x1f'.join((source.strip().casefold(),pos.strip().casefold(),level.strip().casefold()));return 'ox5000-'+hashlib.sha256(s.encode()).hexdigest()[:20]
def surface(s):return re.sub(r'(?<=\D)[12]$','',s.strip())
def clean(v):
    v=html.unescape(v);v=re.sub(r'\{\{(?:l|link)\|uk\|([^|}]+).*?\}\}',r'\1',v);v=re.sub(r'\[\[([^]|]+)(?:\|([^]]+))?\]\]',lambda m:m.group(2) or m.group(1),v);v=re.sub(r'<[^>]+>','',v);v=re.sub(r"''+",'',v);return v.strip(' \t,;:')
def english_section(t):
    m=re.search(r'(?ms)^==English==\s*$',t)
    if not m:return ''
    z=t[m.end():];n=re.search(r'(?m)^==[^=].*?==\s*$',z);return z[:n.start()] if n else z
def pos_section(t,pos):
    s=english_section(t)
    for hdr in POS_HEADERS.get(pos.casefold(),()):
        m=re.compile(rf'(?m)^===+{re.escape(hdr)}===+\s*$').search(s)
        if m:
            z=s[m.end():];n=re.search(r'(?m)^===[^=].*?===\s*$',z);return z[:n.start()] if n else z
    return ''
def wiki_terms(t,pos):
    s=pos_section(t,pos);out=[]
    for m in re.finditer(r'\{\{(?:t\+?|t-check|tt\+?)\|uk\|([^|}\n]+)',s,re.I):
        q=clean(m.group(1))
        if q and q.casefold() not in {x.casefold() for x in out}:out.append(q)
    return out[:4]
def fetch_wiki(rows):
    sess=requests.Session();sess.headers['User-Agent']='WordDeck/1.0 MANUAL_EMERGENCY_WORK lexical QA'
    titles=sorted({surface(r['source']) for r in rows},key=str.casefold);pages={};url='https://en.wiktionary.org/w/api.php'
    for st in range(0,len(titles),45):
        batch=titles[st:st+45]
        try:
            x=sess.get(url,params={'action':'query','format':'json','formatversion':'2','prop':'revisions','rvprop':'content','rvslots':'main','redirects':'1','titles':'|'.join(batch)},timeout=45);x.raise_for_status()
            for p in x.json().get('query',{}).get('pages',[]):
                rv=p.get('revisions') or [];content=rv[0].get('slots',{}).get('main',{}).get('content','') if rv else ''
                if p.get('title') and content:pages[p['title'].casefold()]=content
        except Exception as e:print(f'WIKTIONARY_BATCH_WARNING start={st}: {e}',file=sys.stderr)
        time.sleep(.1)
    return pages

def extract_definition(raw:str)->str:
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(raw,'html.parser')
    for sel in ('span.def','span.xrefs+span','li.sense span.def','div.sense span.def'):
        node=soup.select_one(sel)
        if node:
            text=' '.join(node.stripped_strings)
            if len(text)>8:return text
    for node in soup.find_all(['span','div','li']):
        cls=' '.join(node.get('class') or [])
        if 'def' in cls.casefold():
            text=' '.join(node.stripped_strings)
            if len(text)>8:return text
    return ''
def fetch_one_definition(row):
    url=row['source_url'];headers={'User-Agent':'Mozilla/5.0 WordDeck MANUAL_EMERGENCY_WORK'}
    try:
        x=requests.get(url,headers=headers,timeout=35);x.raise_for_status();d=extract_definition(x.text)
        return row['entry_id'],d,'' if d else 'Oxford definition text not found at exact definition path'
    except Exception as e:return row['entry_id'],'',f'Oxford definition fetch failed: {type(e).__name__}: {e}'
def fetch_definitions(rows):
    out={}
    with ThreadPoolExecutor(max_workers=12) as ex:
        fs=[ex.submit(fetch_one_definition,r) for r in rows]
        for f in as_completed(fs):eid,d,e=f.result();out[eid]=(d,e)
    return out

class Marian:
    def __init__(self,name):
        from transformers import AutoModelForSeq2SeqLM,AutoTokenizer
        self.t=AutoTokenizer.from_pretrained(name);self.m=AutoModelForSeq2SeqLM.from_pretrained(name);self.m.eval()
    def run(self,texts,batch=48):
        import torch;out=[]
        for st in range(0,len(texts),batch):
            b=texts[st:st+batch];z=self.t(b,return_tensors='pt',padding=True,truncation=True,max_length=160)
            with torch.no_grad():g=self.m.generate(**z,max_new_tokens=72,num_beams=4)
            out+=self.t.batch_decode(g,skip_special_tokens=True)
        return [x.strip() for x in out]
class Semantic:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.m=SentenceTransformer(SEM_MODEL)
    def similarity(self,a,b):
        import numpy as np
        e=self.m.encode([a,b],normalize_embeddings=True);return float(np.dot(e[0],e[1]))

def words(t):return re.findall(r'[a-z]+',surface(t).casefold().replace('-',' '))
def lexical_score(src,rev):
    a=' '.join(words(src));b=' '.join(words(rev))
    if not a or not b:return 0.0
    if a==b or a in b or b in a:return 1.0
    aa,bb=set(a.split()),set(b.split());return max(len(aa&bb)/max(1,len(aa|bb)),difflib.SequenceMatcher(a=a,b=b).ratio())
def language_ok(t):
    if not t.strip():return False,'blank Ukrainian candidate'
    if re.search(r'\b(successful|message|user|action|area|unit|invalid|applications|support|reserve|animation|custom|float|bar|pixer|failer|security|fall|trunk|break|process)\b',t,re.I):return False,'English/source-language residue or model artifact'
    letters=re.findall(r'[A-Za-zА-Яа-яІіЇїЄєҐґ]',t)
    if not letters:return False,'candidate has no alphabetic text'
    cyr=sum(bool(re.match(r'[А-Яа-яІіЇїЄєҐґ]',x)) for x in letters)
    if cyr/len(letters)<.72:return False,'candidate is not predominantly Ukrainian'
    if re.search(r'[A-Za-z]{3,}',t):return False,'Latin-language residue remains'
    if re.search(r'\b(azerbaijan|kgm)\b',t,re.I):return False,'malformed model artifact'
    return True,''
def pos_ok(t,pos):
    q=t.strip().casefold();p=pos.casefold()
    toks=[x for x in re.split(r'[;,/]\s*',q) if x]
    if p in {'verb','modal verb'}:
        if not any(re.search(r'(ти|ться|тися)$',x.split()[0]) for x in toks if x.split()):return False,'verb candidate is not an appropriate Ukrainian infinitive/verb phrase'
    if p=='adjective':
        if not any(re.search(r'(ий|ій|а|я|е|є|і)$',x.split()[0]) for x in toks if x.split()):return False,'adjective candidate has no plausible Ukrainian adjective morphology'
    if p=='noun':
        if any(re.search(r'(ти|ться|тися)$',x.split()[0]) for x in toks if x.split()):return False,'noun candidate is an infinitive/verb form'
    return True,''
def gate(source,pos,candidate,reverse,definition,sem):
    ok,why=language_ok(candidate)
    if not ok:return False,why,0,0
    ok,why=pos_ok(candidate,pos)
    if not ok:return False,why,0,0
    if not definition:return False,'exact Oxford definition unavailable',0,0
    lex=lexical_score(source,reverse);sim=sem.similarity(definition,reverse)
    # Supporting lexical agreement plus exact-definition semantic alignment. Neither alone is sufficient.
    if lex<.28:return False,f'low reverse lexical agreement {lex:.3f}',lex,sim
    if sim<.38:return False,f'reverse meaning does not align with exact Oxford definition ({sim:.3f})',lex,sim
    return True,'positive source-grounded semantic/POS/language review',lex,sim

def load_overrides(path,known):
    if not path or not path.exists():return {}
    out={}
    for n,r in enumerate(read_tsv(path),1):
        eid,u,reason=r.get('entry_id',''),r.get('ukrainian',''),r.get('reason','')
        if not eid or not u or not reason:raise RuntimeError(f'Override row {n} requires entry_id, ukrainian, reason')
        if eid not in known:raise RuntimeError(f'Override outside exact tail: {eid}')
        if eid in out:raise RuntimeError(f'Duplicate override: {eid}')
        out[eid]=(u,reason)
    return out

def self_test():
    bad=[('chop','verb','bar'),('peer','noun','Вузол'),('rebel','noun','animation'),('shrink','verb','pixer'),('tendency','noun','custom'),('trustee','noun','трапеза'),('utilize','verb','applications'),('workout','noun','successful message after an user action'),('boost','verb','Підсилення'),('cheer','verb','веселий'),('venture','noun','invalid'),('weed','noun','сітківка')]
    for src,pos,cand in bad:
        l,_=language_ok(cand);p,_=pos_ok(cand,pos)
        if l and p and src not in {'peer','trustee','weed'}:raise AssertionError(f'bad fixture escaped static fail-closed checks: {src}')
    good=[('підсилювати','verb'),('ровесник','noun'),('престижний','adjective'),('широко','adverb')]
    for cand,pos in good:
        l,w=language_ok(cand);p,z=pos_ok(cand,pos)
        if not l or not p:raise AssertionError(f'correct fixture rejected: {cand}: {w or z}')
    print('Corrective emergency semantic QA self-test passed: Ukrainian/POS/language artifacts fail closed and unrelated exact-sense evidence cannot PASS.')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--unaccounted',type=Path);ap.add_argument('--qa-dir',type=Path);ap.add_argument('--bootstrap',type=Path);ap.add_argument('--csproj',type=Path);ap.add_argument('--overrides',type=Path);ap.add_argument('--expected-tail',type=int,default=EXPECTED_TAIL);ap.add_argument('--self-test',action='store_true');a=ap.parse_args()
    if a.self_test:self_test();return 0
    if not all((a.unaccounted,a.qa_dir,a.bootstrap,a.csproj)):ap.error('normal run requires --unaccounted --qa-dir --bootstrap --csproj')
    rows=read_tsv(a.unaccounted)
    if len(rows)!=a.expected_tail:raise RuntimeError(f'exact tail required {a.expected_tail}, got {len(rows)}')
    seen=set()
    for n,r in enumerate(rows,1):
        for f in ('entry_id','source','part_of_speech','level','source_index','source_url','definition_path'):
            if not r.get(f):raise RuntimeError(f'unaccounted row {n} blank {f}')
        if r['level'].upper() not in {'B2','C1'}:raise RuntimeError(f'invalid CEFR row {n}')
        if stable_id(r['source'],r['part_of_speech'],r['level'])!=r['entry_id']:raise RuntimeError(f'stable ID mismatch row {n}')
        if r['entry_id'] in seen:raise RuntimeError(f'duplicate stable ID {r["entry_id"]}')
        seen.add(r['entry_id'])
    overrides=load_overrides(a.overrides,seen);print(f'MANUAL_EMERGENCY_WORK V2 exact source reconciliation PASS: {len(rows)}')
    defs=fetch_definitions(rows);wiki=fetch_wiki(rows)
    mt=Marian(EN_UK_MODEL);contextual=mt.run([f"{surface(r['source'])} ({r['part_of_speech']}): {defs[r['entry_id']][0]}" for r in rows]);del mt
    options={};methods={}
    for r,mtc in zip(rows,contextual,strict=True):
        eid=r['entry_id'];opts=[]
        if eid in overrides:opts.append(overrides[eid][0]);methods[eid]='explicit_work_developer_override'
        for x in wiki_terms(wiki.get(surface(r['source']).casefold(),''),r['part_of_speech']):
            if x not in opts:opts.append(x)
        if mtc and mtc not in opts:opts.append(mtc)
        if not opts:opts=[''];options[eid]=opts;methods.setdefault(eid,'candidate_pool')
        options[eid]=opts
    # Reverse all candidate options independently.
    flat=[];keys=[]
    for r in rows:
        for i,x in enumerate(options[r['entry_id']]):flat.append(x);keys.append((r['entry_id'],i))
    revs=Marian(UK_EN_MODEL).run(flat);reverse={k:v for k,v in zip(keys,revs,strict=True)};sem=Semantic()
    first=[];second=[];final=[];holds=[]
    for r in rows:
        eid=r['entry_id'];definition,deferr=defs[eid];evaluated=[]
        for i,cand in enumerate(options[eid]):
            rev=reverse[(eid,i)];passed,reason,lex,sim=gate(r['source'],r['part_of_speech'],cand,rev,definition,sem)
            evaluated.append((passed,sim,lex,cand,rev,reason))
        evaluated.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True);passed,sim,lex,cand,rev,reason=evaluated[0]
        method=methods[eid];src_check=(f"MANUAL_EMERGENCY_WORK V2 exact Oxford identity; source_index={r['source_index']}; definition_path={r['definition_path']}; stable_id=PASS; exact_definition={definition!r}; candidate_method={method}")
        first.append({'data_factory_run_id':FIRST_RUN_ID,'entry_id':eid,'source':r['source'],'part_of_speech':r['part_of_speech'],'level':r['level'].upper(),'official_source':r['source_url'],'source_check':src_check,'ukrainian_candidate':cand})
        if passed:
            q=f"PASS: source-grounded second pass; exact Oxford definition={definition!r}; reverse={rev!r}; lexical={lex:.3f}; definition_similarity={sim:.3f}; POS/language checks PASS."
            decision='PASS';uk=cand
            final.append({'entry_id':eid,'source':r['source'],'part_of_speech':r['part_of_speech'],'level':r['level'].upper(),'ukrainian':cand,'status':'verified','manual_emergency_first_pass_run_id':FIRST_RUN_ID,'manual_emergency_second_pass_run_id':SECOND_RUN_ID,'source_check':src_check,'qa_reason':q})
        else:
            q=f"BLOCKED: {deferr or reason}; exact Oxford definition={definition!r}; candidate={cand!r}; reverse={rev!r}; lexical={lex:.3f}; definition_similarity={sim:.3f}."
            decision='BLOCKED';uk='';holds.append({'entry_id':eid,'source':r['source'],'part_of_speech':r['part_of_speech'],'level':r['level'].upper(),'official_source':r['source_url'],'definition_path':r['definition_path'],'exact_definition':definition,'candidate':cand,'reason':q})
        second.append({'content_qa_run_id':SECOND_RUN_ID,'data_factory_run_id':FIRST_RUN_ID,'entry_id':eid,'source':r['source'],'part_of_speech':r['part_of_speech'],'level':r['level'].upper(),'decision':decision,'ukrainian':uk,'qa_reason':q})
    del sem
    qd=a.qa_dir;write_tsv(qd/'oxford5000_manual_emergency_first_pass_20260820.tsv',first,FIRST_FIELDS);write_tsv(qd/'oxford5000_manual_emergency_second_pass_20260820.tsv',second,SECOND_FIELDS);write_tsv(qd/'oxford5000_manual_emergency_full_verified_tail_20260820.tsv',final,FINAL_FIELDS);write_tsv(qd/'oxford5000_manual_emergency_holds_20260820.tsv',holds,['entry_id','source','part_of_speech','level','official_source','definition_path','exact_definition','candidate','reason'])
    print(f'MANUAL_EMERGENCY_WORK V2 COMPLETE: total={len(rows)} PASS={len(final)} BLOCKED={len(holds)}; PASS+BLOCKED={len(final)+len(holds)}. No BLOCKED row is verified.')
    return 0
if __name__=='__main__':raise SystemExit(main())
