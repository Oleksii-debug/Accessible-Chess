#!/usr/bin/env python3
"""V8b: finish the exact 1134-row tail after recovering five missing Oxford definitions."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import run_oxford5000_v8_completion as core


def read_tsv(path: Path) -> list[dict[str,str]]:
    with path.open('r',encoding='utf-8-sig',newline='') as h:
        return [{k:(v or '').strip() for k,v in row.items()} for row in csv.DictReader(h,delimiter='\t')]


def write_tsv(path: Path, rows: list[dict[str,str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as h:
        w=csv.DictWriter(h,fieldnames=fields,delimiter='\t',lineterminator='\n',extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def recover_input(source: Path, recovery_path: Path, target: Path) -> dict[str,str]:
    rows=read_tsv(source); recovery=read_tsv(recovery_path); fixes={r['entry_id']:r for r in recovery}
    if len(fixes)!=5: raise RuntimeError(f'Expected exactly 5 definition recovery rows, got {len(fixes)}')
    fixed=[]
    for row in rows:
        if not row.get('exact_definition'):
            item=fixes.get(row['entry_id'])
            if item is None: raise RuntimeError(f'No recovered exact definition for {row["entry_id"]}')
            row['exact_definition']=item['exact_definition']
            row['official_source']=item['official_source']
            row['definition_path']=item['official_source']
        fixed.append(row)
    if any(not r.get('exact_definition') for r in fixed): raise RuntimeError('Recovered V8 input still contains blank exact_definition')
    if len(fixed)!=1134: raise RuntimeError(f'Expected 1134 unresolved rows, got {len(fixed)}')
    fields=list(fixed[0].keys()); write_tsv(target,fixed,fields)
    return {r['entry_id']:r['exact_definition'] for r in recovery}


def main() -> int:
    core.TMP.mkdir(parents=True,exist_ok=True); core.ART.mkdir(parents=True,exist_ok=True)
    core.run('git','config','user.name','github-actions[bot]'); core.run('git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    core.run('python','WordDeck/tools/fetch_oxford5000_official_html.py','--output',str(core.TMP/'official.html'))
    start_runtime,_,start_unaccounted=core.ledger('start')
    start_n=core.count_rows(start_runtime); remaining=core.count_rows(start_unaccounted)
    if start_n!=1004 or remaining!=1134: raise RuntimeError(f'V8b expects technical V7 state 1004/1134, got {start_n}/{remaining}')
    unresolved=core.WORDDECK/'QA'/'oxford5000_manual_emergency_v7_final_unresolved.tsv'
    recovery=core.WORDDECK/'QA'/'oxford5000_manual_emergency_v8_definition_recovery.tsv'
    fixed=core.TMP/'v8-fixed-unresolved.tsv'; recovered=recover_input(unresolved,recovery,fixed)
    unacc_ids={line.split('\t',1)[0] for line in start_unaccounted.read_text(encoding='utf-8-sig').splitlines()[1:] if line.strip()}
    fixed_ids={line.split('\t',1)[0] for line in fixed.read_text(encoding='utf-8-sig').splitlines()[1:] if line.strip()}
    if unacc_ids!=fixed_ids: raise RuntimeError('V8b recovered input IDs do not equal exact live unaccounted ledger')
    core.write_json(core.ART/'definition-recovery.json',{'count':5,'definitions':recovered,'provenance':'official Oxford pages; additive recovery, V7 evidence preserved unchanged'})
    core.run('python','WordDeck/tools/validate_oxford3000_baseline_files.py','--report',str(core.TMP/'oxford3000-start.tsv'))

    qadir=core.TMP/'content'; qadir.mkdir(parents=True,exist_ok=True)
    core.run('python','WordDeck/tools/complete_oxford5000_emergency_v8.py','--input',str(fixed),'--qa-dir',str(qadir))
    summary=json.loads((qadir/'summary.json').read_text(encoding='utf-8'))
    if int(summary['pass'])!=1134 or int(summary['blocked'])!=0: raise RuntimeError(f'V8b must resolve entire 1134-row tail: {summary}')
    integrated,checkpoints=core.integrate_all(qadir,start_runtime,start_unaccounted,1134)
    final_runtime,final_accounting,final_unaccounted=core.ledger('final')
    final_n=core.count_rows(final_runtime); final_remaining=core.count_rows(final_unaccounted)
    if integrated!=1134 or final_n!=2138 or final_remaining!=0: raise RuntimeError(f'V8b lexical completion mismatch integrated={integrated} final={final_n}/{final_remaining}')
    shutil.copyfile(final_runtime,core.ART/'final-runtime.tsv'); shutil.copyfile(final_accounting,core.ART/'final-accounting.tsv'); shutil.copyfile(final_unaccounted,core.ART/'final-unaccounted.tsv'); shutil.copyfile(qadir/'review-evidence.tsv',core.ART/'v8-review-evidence.tsv')
    core.run('python','WordDeck/tools/validate_oxford3000_baseline_files.py','--report',str(core.ART/'oxford3000-final.tsv'))

    final_sha=core.ensure_full_audio_request(); audio_info,audio_artifacts=core.wait_audio(final_sha)
    final={'start_activated':1004,'start_remaining':1134,'recovered_missing_definitions':5,'v8_reviewed':1134,'v8_second_semantic_qa':1134,'newly_activated_v8':1134,'final_activated':2138,'final_remaining':0,'checkpoint_count':len(checkpoints),'checkpoints':checkpoints,'final_sha':final_sha,'audio_complete':True,'audio_run_id':int(audio_info['id']),'audio_covered_ids':2138,'audio_assets':2138,'audio_required_artifacts':['worddeck-oxford5000-en-gb-0-0','WordDeck-win-x64-with-oxford5000-audio'],'provenance':'WORK_DEVELOPER_MANUAL_EMERGENCY_CONTEXTUAL_REVIEW; second reverse-semantic QA; not AUTO_DATA_FACTORY/AUTO_CONTENT_QA'}
    core.write_json(core.ART/'final-summary.json',final)
    with core.GH_ENV.open('a',encoding='utf-8') as h:
        h.write(f"FINAL_RUNTIME=2138\nFINAL_REMAINING=0\nFINAL_SHA={final_sha}\nTOTAL_INTEGRATED=1134\nAUDIO_RUN_ID={audio_info['id']}\nAUDIO_COMPLETE=true\n")
    print(json.dumps(final,ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
