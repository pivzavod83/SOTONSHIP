#!/usr/bin/env python3
"""Fetch pinned public source-pair benchmark; raw code remains in ignored cache."""
from __future__ import annotations
import argparse,hashlib,json,subprocess
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
COMMIT='2b14b7bf7e55556205654c6f7657fa60e36251fa'
BASE=f'https://raw.githubusercontent.com/COBOL-Coder/COBOL-Coder/{COMMIT}/'
PATH='evaluation/data/COBOL-JavaTrans.jsonl'

def fetch(cache: Path):
    cache.mkdir(parents=True,exist_ok=True)
    for remote,local in ((PATH,'COBOL-JavaTrans.jsonl'),('LICENSE','LICENSE-COBOL-Coder.txt')):
        data=subprocess.run(['curl','--fail','--location','--silent','--show-error','--max-time','60',BASE+remote],check=True,capture_output=True).stdout
        (cache/local).write_bytes(data)
    human=subprocess.run(['curl','--fail','--location','--silent','--show-error','--max-time','60','https://raw.githubusercontent.com/openai/human-eval/b9453e8f1865df0a0057a1383767caa400acfbcf/LICENSE'],check=True,capture_output=True).stdout
    (cache/'LICENSE-HumanEval.txt').write_bytes(human)
    data=(cache/'COBOL-JavaTrans.jsonl').read_bytes()
    if hashlib.sha256(data).hexdigest()!='ff1b2e308ea006d905fd979103f32486c57d586c5fdbc0325a23f8ae23a6530d':
        raise ValueError('Pinned dataset content hash mismatch')
    rows=[json.loads(line) for line in data.decode().splitlines() if line.strip()]
    if len(rows)!=143 or len({r['task_id'] for r in rows})!=143:
        raise ValueError('Pinned benchmark must contain 143 unique task pairs')
    manifest={'dataset':'COBOL-JavaTrans','records':len(rows),'repository':'https://github.com/COBOL-Coder/COBOL-Coder',
      'commit':COMMIT,'path':PATH,'url':BASE+PATH,'sha256':hashlib.sha256(data).hexdigest(),
      'collectionDate':datetime.now(timezone.utc).date().isoformat(),'repositoryLicense':'Apache-2.0','humanEvalLicenseCommit':'b9453e8f1865df0a0057a1383767caa400acfbcf','underlyingTasks':'HumanEval (MIT); upstream benchmark translations are not independently audited',
      'rawCache':'evaluation/corpora/cobol-javatrans/','use':'paired-source contrastive correspondence training and task-grouped evaluation; not equivalence labels'}
    target=ROOT/'evaluation'/'paired-code'/'dataset-manifest.json'; target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'records':len(rows),'sha256':manifest['sha256'],'cache':str(cache)}))
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cache',type=Path,default=ROOT/'evaluation/corpora/cobol-javatrans')
    fetch(parser.parse_args().cache)
