#!/usr/bin/env python3
"""Evaluate the frozen checkpoint, including a disclosed declaration-rename control.

This reuses the already observed 29-task test split. It is not a new independent
holdout, financial validation, or a reason to adjust weights/thresholds.
"""
from __future__ import annotations
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,re,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ml_engine.code_graph import build_graph,clean_source
from ml_engine.paired_gnn import encode_graph,load_model,model_metadata
from scripts.train_paired_gnn import metrics,name_tokens


def anonymise_java(source):
    source=clean_source(source,'java')
    source=re.sub(r'\b(class|interface)\s+\w+',r'\1 OpaqueClass',source)
    return re.sub(r'((?:public|private|protected)\s+(?:static\s+)?[\w<>\[\], ?]+\s+)\w+(?=\s*\()',r'\1 opaque',source)


def evaluate(dataset):
    raw=dataset.read_bytes();manifest=json.loads((ROOT/'evaluation/paired-code/dataset-manifest.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:raise ValueError('Pinned dataset hash mismatch')
    byid={row['task_id']:row for row in (json.loads(line) for line in raw.decode().splitlines() if line.strip())}
    split=json.loads((ROOT/'evaluation/paired-code/task-splits.json').read_text());ids=split['splits']['test']
    rows=[byid[identifier] for identifier in ids];model=load_model();vectors=[[],[],[]];hist=[[],[],[]]
    for row in rows:
        sources=((row['COBOL_canonical_solution'],'cobol'),(row['Java_canonical_solution'],'java'),(anonymise_java(row['Java_canonical_solution']),'java'))
        for k,(source,language) in enumerate(sources):
            graph=build_graph(source,language);vectors[k].append(encode_graph(graph,model));hist[k].append(graph.x.mean(axis=0))
    vectors=[np.stack(v) for v in vectors];hist=[np.stack(v) for v in hist]
    delta=float(np.max(np.abs(vectors[1]-vectors[2])))
    if delta>1e-10:raise ValueError('Declaration renaming changed learned features: investigate leakage before reporting')
    for values in hist:values/=np.maximum(np.linalg.norm(values,axis=1,keepdims=True),1e-9)
    cn=[name_tokens(r['COBOL_canonical_solution'],'cobol') for r in rows]
    names=[name_tokens(r['Java_canonical_solution'],'java') for r in rows]
    renamed=[name_tokens(anonymise_java(r['Java_canonical_solution']),'java') for r in rows]
    def name_metrics(candidates):
        scores=np.asarray([[len(a&b)/max(1,len(a|b)) for b in candidates] for a in cn])
        return metrics(scores)
    result={'model':model_metadata(model),'evaluatedAt':datetime.now(timezone.utc).isoformat(),
        'datasetSha256':manifest['sha256'],'candidateOrder':ids,'queries':len(rows),'candidatesPerQuery':len(rows),
        'originalNames':{'gnn':metrics(vectors[0]@vectors[1].T),'nameMatching':name_metrics(names),'semanticHistogram':metrics(hist[0]@hist[1].T)},
        'anonymisedJavaDeclarations':{'gnn':metrics(vectors[0]@vectors[2].T),'nameMatching':name_metrics(renamed),'semanticHistogram':metrics(hist[0]@hist[2].T)},
        'maximumEmbeddingDifference':delta,
        'method':'Remove comments and rename Java class/method declarations; retain implementations, external API calls and COBOL. Frozen weights and thresholds. Stable stored test-task candidate order breaks ties.',
        'limitations':['Controlled name-unavailability stress test, not representative real-world deployment evidence',
                       'Same previously observed 29 test tasks, not a fresh independent holdout',
                       'Name matching is deliberately deprived of its signal; original 93% performance remains visible',
                       'No no-message ablation stress claim: that checkpoint is not stored',
                       'Financial-domain matching remains unvalidated; rankings require engineer confirmation']}
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--dataset',type=Path,default=ROOT/'evaluation/corpora/cobol-javatrans/COBOL-JavaTrans.jsonl')
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/paired-code/rename-stress-report.json');args=parser.parse_args()
    result=evaluate(args.dataset)
    temporary=args.output.with_suffix('.json.tmp');temporary.write_text(json.dumps(result,indent=2)+'\n');temporary.replace(args.output)
    print(json.dumps({k:result[k] for k in ('originalNames','anonymisedJavaDeclarations','maximumEmbeddingDifference')}))
