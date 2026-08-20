#!/usr/bin/env python3
"""Execute the heavy Oxford 5000 V4 corrective run inside GitHub Actions.

This runner is orchestration only. Lexical judgement lives in
complete_oxford5000_emergency_v4.py. It preserves <=120-row recovery checkpoints,
requires exact-head authoritative Windows CI before each next mutation, and only
requests the full British AudioPack when the lexical tail reaches zero.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT=Path.cwd(); WORDDECK=ROOT/'WordDeck'; TMP=Path('/tmp/worddeck-v4'); ART=ROOT/'artifacts'/'emergency-v4'; REPO=os.environ['GITHUB_REPOSITORY']; GH_ENV=Path(os.environ['GITHUB_ENV'])

def run(*args:str,capture:bool=False)->str:
    result=subprocess.run(args,cwd=ROOT,text=True,check=True,stdout=subprocess.PIPE if capture else None)
    return (result.stdout or '').strip()

def count_rows(path:Path)->int:
    with path.open('r',encoding='utf-8-sig') as handle:return max(0,sum(1 for _ in handle)-1)

def gh_json(endpoint:str)->dict:return json.loads(run('gh','api',endpoint,capture=True))

def write_json(path:Path,value:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def wait_windows_ci(sha:str)->tuple[dict,dict]:
    run_id=None
    for _ in range(180):
        payload=gh_json(f'repos/{REPO}/actions/workflows/worddeck-windows.yml/runs?branch=worddeck-bootstrap&event=push&per_page=50')
        for item in payload.get('workflow_runs',[]):
            if item.get('head_sha')==sha:run_id=int(item['id']);break
        if run_id:break
        time.sleep(5)
    if not run_id:raise RuntimeError(f'No authoritative Windows run found for exact HEAD {sha}')
    for _ in range(240):
        info=gh_json(f'repos/{REPO}/actions/runs/{run_id}')
        if info.get('status')=='completed':
            if info.get('conclusion')!='success':raise RuntimeError(f'Windows run {run_id} failed for {sha}: {info.get("conclusion")}')
            artifacts=gh_json(f'repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100'); write_json(ART/f'windows-run-{sha}.json',info); write_json(ART/f'windows-artifacts-{sha}.json',artifacts)
            with (ART/'windows-run-ids.txt').open('a',encoding='utf-8') as handle:handle.write(f'{sha}\t{run_id}\n')
            return info,artifacts
        time.sleep(10)
    raise RuntimeError(f'Timed out waiting for authoritative Windows run {run_id}')

def ledger(prefix:str)->tuple[Path,Path,Path]:
    runtime=TMP/f'{prefix}-runtime.tsv'; accounting=TMP/f'{prefix}-accounting.tsv'; unaccounted=TMP/f'{prefix}-unaccounted.tsv'
    run('python','WordDeck/tools/validate_oxford5000_runtime_ledger.py','--official-html',str(TMP/'official.html'),'--ledger',str(runtime),'--report',str(accounting),'--unaccounted',str(unaccounted)); return runtime,accounting,unaccounted

def rename_manual_slices(txdir:Path,round_id:str)->None:
    op=txdir/'orchestration.json'; tp=txdir/'transaction'/'transaction.json'; sp=txdir/'transaction'/'prepared-slices'; orch=json.loads(op.read_text(encoding='utf-8')); tx=json.loads(tp.read_text(encoding='utf-8')); by_index={}
    for checkpoint in tx['checkpoints']:
        old=checkpoint['file_name']; new=old.replace('oxford5000_source_after_auto_',f'oxford5000_source_after_manual_v4_{round_id}_')
        if new==old:raise RuntimeError(f'Unexpected prepared filename {old}')
        (sp/old).rename(sp/new); checkpoint['file_name']=new; by_index[int(checkpoint['index'])]=new
    for checkpoint in orch['checkpoints']:checkpoint['file']=by_index[int(checkpoint['index'])]
    write_json(tp,tx); write_json(op,orch)

def stage_round_evidence(qadir:Path,round_id:str)->list[str]:
    mapping={'first-pass.tsv':f'WordDeck/QA/oxford5000_manual_emergency_v4_{round_id}_first_pass.tsv','second-pass.tsv':f'WordDeck/QA/oxford5000_manual_emergency_v4_{round_id}_second_pass.tsv','holds.tsv':f'WordDeck/QA/oxford5000_manual_emergency_v4_{round_id}_holds.tsv','summary.json':f'WordDeck/QA/oxford5000_manual_emergency_v4_{round_id}_summary.json'}; targets=[]
    for source,target in mapping.items():shutil.copyfile(qadir/source,ROOT/target);targets.append(target)
    return targets

def write_audio_request()->None:
    path=WORDDECK/'Audio'/'generation-request.json'; path.write_text(json.dumps({'source':'oxford5000','start':0,'limit':0,'accent':'en-GB','femaleVoice':'bf_emma','maleVoice':'bm_george','speed':1.0,'format':'mp3'},indent=2)+'\n',encoding='utf-8')

def integrate_round(round_id:str,qadir:Path,pre_runtime:Path,pre_unaccounted:Path,blocked_count:int)->int:
    txdir=TMP/f'tx-{round_id}'; run('python','WordDeck/tools/orchestrate_oxford5000_bulk_run.py','start','--worddeck-dir','WordDeck','--run-dir',str(txdir),'--official-html',str(TMP/'official.html'),'--pre-runtime',str(pre_runtime),'--pre-unaccounted',str(pre_unaccounted),'--data-factory',str(qadir/'first-pass.tsv'),'--content-qa',str(qadir/'second-pass.tsv'),'--checkpoint-size','120'); rename_manual_slices(txdir,round_id); plan=json.loads((txdir/'orchestration.json').read_text(encoding='utf-8')); checkpoints=plan['checkpoints']
    if not checkpoints:raise RuntimeError('V4 PASS set unexpectedly produced zero checkpoints')
    for ordinal,checkpoint in enumerate(checkpoints,1):
        run('python','WordDeck/tools/orchestrate_oxford5000_bulk_run.py','apply-next','--worddeck-dir','WordDeck','--run-dir',str(txdir)); filename=checkpoint['file']; paths=['WordDeck/ReviewedOxford5000Bootstrap.cs','WordDeck/WordDeck.csproj',f'WordDeck/QA/{filename}']
        if ordinal==1:paths.extend(stage_round_evidence(qadir,round_id))
        if blocked_count==0 and ordinal==len(checkpoints):write_audio_request();paths.append('WordDeck/Audio/generation-request.json')
        run('git','add','--',*paths); run('git','diff','--cached','--check'); run('git','commit','-m',f'WordDeck: integrate V4 Oxford 5000 {round_id} checkpoint {ordinal:02d}'); sha=run('git','rev-parse','HEAD',capture=True); run('git','push','origin','HEAD:worddeck-bootstrap'); info,artifacts=wait_windows_ci(sha); run_json=TMP/'ci-run.json'; artifacts_json=TMP/'ci-artifacts.json'; write_json(run_json,info); write_json(artifacts_json,artifacts); run('python','WordDeck/tools/orchestrate_oxford5000_bulk_run.py','mark-ci-green','--worddeck-dir','WordDeck','--run-dir',str(txdir),'--run-json',str(run_json),'--artifacts-json',str(artifacts_json))
    run('python','WordDeck/tools/orchestrate_oxford5000_bulk_run.py','finalize','--worddeck-dir','WordDeck','--run-dir',str(txdir)); shutil.copyfile(txdir/'final-summary.json',ART/f'{round_id}-orchestration-final-summary.json'); return sum(int(item['rows']) for item in checkpoints)

def wait_audio(final_sha:str)->tuple[dict,dict]:
    run_id=None
    for _ in range(240):
        payload=gh_json(f'repos/{REPO}/actions/workflows/worddeck-audio.yml/runs?branch=worddeck-bootstrap&event=push&per_page=50')
        for item in payload.get('workflow_runs',[]):
            if item.get('head_sha')==final_sha:run_id=int(item['id']);break
        if run_id:break
        time.sleep(5)
    if not run_id:raise RuntimeError(f'No audio workflow found for exact final HEAD {final_sha}')
    for _ in range(360):
        info=gh_json(f'repos/{REPO}/actions/runs/{run_id}')
        if info.get('status')=='completed':
            if info.get('conclusion')!='success':raise RuntimeError(f'Audio workflow {run_id} failed: {info.get("conclusion")}')
            artifacts=gh_json(f'repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100'); names={a.get('name') for a in artifacts.get('artifacts',[]) if not a.get('expired')}; required={'worddeck-oxford5000-en-gb-0-0','WordDeck-win-x64-with-oxford5000-audio'}
            if not required<=names:raise RuntimeError(f'Audio run missing required nonexpired artifacts: {sorted(required-names)}')
            write_json(ART/'final-audio-run.json',info);write_json(ART/'final-audio-artifacts.json',artifacts);return info,artifacts
        time.sleep(10)
    raise RuntimeError(f'Timed out waiting for full audio workflow {run_id}')

def main()->int:
    TMP.mkdir(parents=True,exist_ok=True);ART.mkdir(parents=True,exist_ok=True);run('git','config','user.name','github-actions[bot]');run('git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com');run('python','WordDeck/tools/fetch_oxford5000_official_html.py','--output',str(TMP/'official.html'));start_runtime,_,start_unaccounted=ledger('start')
    if count_rows(start_runtime)!=982 or count_rows(start_unaccounted)!=1156:raise RuntimeError('V4 must start from exact auditor-trusted 982/1156 baseline')
    run('python','WordDeck/tools/validate_oxford3000_baseline_files.py','--report',str(TMP/'oxford3000-start.tsv'))
    if 'rows\t3308' not in (TMP/'oxford3000-start.tsv').read_text(encoding='utf-8'):raise RuntimeError('Oxford3000 frozen baseline drift')
    run('python','WordDeck/tools/complete_oxford5000_emergency_v4.py','--self-test');initial_sha=run('git','rev-parse','HEAD',capture=True);wait_windows_ci(initial_sha);total_integrated=0;round_summaries=[]
    for number in (1,2):
        round_id=f'round{number:02d}';pre_runtime,_,pre_unaccounted=ledger(f'{round_id}-pre');remaining=count_rows(pre_unaccounted)
        if remaining==0:break
        qadir=TMP/round_id;qadir.mkdir(parents=True,exist_ok=True);args=['python','WordDeck/tools/complete_oxford5000_emergency_v4.py','--unaccounted',str(pre_unaccounted),'--qa-dir',str(qadir),'--expected-tail',str(remaining),'--round-id',round_id];overrides=WORDDECK/'QA'/'oxford5000_manual_emergency_overrides_20260820.tsv'
        if overrides.is_file():args+=['--overrides',str(overrides)]
        run(*args);summary=json.loads((qadir/'summary.json').read_text(encoding='utf-8'));passed=int(summary['pass']);blocked=int(summary['blocked'])
        if passed+blocked!=remaining:raise RuntimeError('V4 PASS/BLOCKED partition does not reconcile exact current tail')
        round_summaries.append(summary);shutil.copyfile(qadir/'summary.json',ART/f'{round_id}-semantic-summary.json');shutil.copyfile(qadir/'holds.tsv',ART/f'{round_id}-holds.tsv');shutil.copyfile(qadir/'second-pass.tsv',ART/f'{round_id}-second-pass.tsv');print(f'V4 {round_id}: total={remaining} PASS={passed} BLOCKED={blocked}')
        if passed==0:break
        integrated=integrate_round(round_id,qadir,pre_runtime,pre_unaccounted,blocked)
        if integrated!=passed:raise RuntimeError(f'Integrated checkpoint rows {integrated} != V4 PASS {passed}')
        total_integrated+=integrated;post_runtime,_,post_unaccounted=ledger(f'{round_id}-post');after=count_rows(post_unaccounted)
        if count_rows(post_runtime)+after!=2138:raise RuntimeError('Post-round Oxford5000 equation drift')
        if remaining-after!=passed:raise RuntimeError('Runtime increase/unaccounted reduction does not equal V4 PASS count')
        if after==0:break
    final_runtime_path,final_accounting,final_unaccounted_path=ledger('final');shutil.copyfile(final_runtime_path,ART/'final-runtime.tsv');shutil.copyfile(final_accounting,ART/'final-accounting.tsv');shutil.copyfile(final_unaccounted_path,ART/'final-unaccounted.tsv');run('python','WordDeck/tools/validate_oxford3000_baseline_files.py','--report',str(ART/'oxford3000-final.tsv'));final_runtime=count_rows(final_runtime_path);final_remaining=count_rows(final_unaccounted_path)
    if final_runtime+final_remaining!=2138:raise RuntimeError('Final Oxford5000 equation does not equal 2138')
    final_sha=run('git','rev-parse','HEAD',capture=True);audio_run_id=''
    if final_remaining==0:audio_info,_=wait_audio(final_sha);audio_run_id=str(audio_info['id'])
    final={'start_activated':982,'start_remaining':1156,'newly_activated_v4':total_integrated,'final_activated':final_runtime,'final_remaining':final_remaining,'final_sha':final_sha,'rounds':round_summaries,'audio_complete':final_remaining==0,'audio_run_id':audio_run_id};write_json(ART/'final-summary.json',final)
    with GH_ENV.open('a',encoding='utf-8') as handle:handle.write(f'FINAL_RUNTIME={final_runtime}\nFINAL_REMAINING={final_remaining}\nFINAL_SHA={final_sha}\nTOTAL_INTEGRATED={total_integrated}\nAUDIO_RUN_ID={audio_run_id}\n')
    print(json.dumps(final,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
