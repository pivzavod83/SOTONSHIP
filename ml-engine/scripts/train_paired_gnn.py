#!/usr/bin/env python3
"""Train source-pair retrieval; splits and choices are fixed before test evaluation.

No synthetic records/labels or source names enter the encoder. The benchmark's
pairing is a correspondence label, not a formal-equivalence guarantee.
"""
from __future__ import annotations
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import argparse,copy,hashlib,json,re,sys,time
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ml_engine.code_graph import build_graph,clean_source,TOKEN,KEYWORDS,FEATURE_NAMES,RELATIONS
from ml_engine.paired_gnn import batch_graphs,initialise,forward,backward,paired_loss,MODEL_PATH


def normalised_shingles(source):
    text=clean_source(source,'java').lower()
    words=[]
    for token in TOKEN.findall(text):
        if re.match(r'[a-z_]',token) and token not in KEYWORDS: token='IDENT'
        words.append(token)
    return {tuple(words[i:i+5]) for i in range(max(1,len(words)-4))}


def split_tasks(rows,seed):
    # Conservative lexical near-duplicates are grouped transitively before split.
    sets=[normalised_shingles(r['Java_canonical_solution']) for r in rows]
    parent=list(range(len(rows)))
    def root(i):
        while parent[i]!=i: parent[i]=parent[parent[i]];i=parent[i]
        return i
    links=[]
    for i in range(len(rows)):
        for j in range(i):
            similarity=len(sets[i]&sets[j])/max(1,len(sets[i]|sets[j]))
            if similarity>=.80:
                parent[root(i)]=root(j);links.append([rows[i]['task_id'],rows[j]['task_id'],round(similarity,6)])
    groups={}
    for i in range(len(rows)): groups.setdefault(root(i),[]).append(i)
    group_values=list(groups.values());np.random.default_rng(seed).shuffle(group_values)
    splits={'train':[],'validation':[],'test':[]}
    # Assign whole duplicate groups; target60/20/20, no source-derived fitting.
    for group in sorted(group_values,key=len,reverse=True):
        key=min(splits,key=lambda k:len(splits[k])/({'train':.6,'validation':.2,'test':.2}[k]*len(rows)))
        splits[key].extend(group)
    return {k:sorted(v) for k,v in splits.items()},list(groups.values()),links


def metrics(scores):
    n=len(scores); order=np.argsort(-scores,axis=1,kind='stable')
    ranks=np.asarray([np.where(order[i]==i)[0][0]+1 for i in range(n)])
    return {'queries':n,'candidatesPerQuery':n,'top1':round(float(np.mean(ranks==1)),6),
            'top3':round(float(np.mean(ranks<=min(3,n))),6),'top5':round(float(np.mean(ranks<=min(5,n))),6),
            'mrr':round(float(np.mean(1/ranks)),6)}


def fit(graphs,split,seed,epochs,message_passing):
    c,j=graphs; train=split['train'];val=split['validation']
    bt=[batch_graphs([g[i] for i in train],message_passing) for g in (c,j)]
    bv=[batch_graphs([g[i] for i in val],message_passing) for g in (c,j)]
    params=initialise(seed);m={k:np.zeros_like(v) for k,v in params.items()};v=copy.deepcopy(m)
    best=None;bestkey=None;history=[]
    for epoch in range(1,epochs+1):
        cv,cc=forward(bt[0],params,True);jv,jc=forward(bt[1],params,True)
        loss,dc,dj=paired_loss(cv,jv); gc=backward(dc,cc,params);gj=backward(dj,jc,params)
        for name in params:
            gradient=gc[name]+gj[name]+1e-4*params[name]
            gradient=np.clip(gradient,-5,5)
            m[name]=.9*m[name]+.1*gradient;v[name]=.999*v[name]+.001*gradient**2
            params[name]-=.004*(m[name]/(1-.9**epoch))/(np.sqrt(v[name]/(1-.999**epoch))+1e-8)
        if epoch==1 or epoch%10==0:
            vc=forward(bv[0],params);vj=forward(bv[1],params);score=vc@vj.T
            vm=metrics(score);vl=paired_loss(vc,vj)[0]
            history.append({'epoch':epoch,'trainLoss':round(loss,6),'validationLoss':round(vl,6),**vm})
            key=(vm['mrr'],-vl)
            if bestkey is None or key>bestkey: bestkey=key;best=copy.deepcopy(params);best_epoch=epoch
            if epoch%50==0: print(json.dumps({'messagePassing':message_passing,**history[-1]}),flush=True)
    return best,best_epoch,history


def name_tokens(source,language):
    if language=='cobol': match=re.search(r'PROGRAM-ID\.\s*([\w-]+)',source,re.I)
    else: match=re.search(r'public\s+(?:static\s+)?[\w<>\[\], ?]+\s+(\w+)\s*\(',source)
    name=match.group(1) if match else ''
    return set(re.sub(r'([a-z])([A-Z])',r'\1 \2',name).lower().replace('_',' ').replace('-',' ').split())


def evaluate(rows,graphs,indices,params,message_passing=True):
    c,j=graphs
    cv=forward(batch_graphs([c[i] for i in indices],message_passing),params)
    jv=forward(batch_graphs([j[i] for i in indices],message_passing),params)
    return cv@jv.T


def thresholds(scores):
    n=len(scores);order=np.argsort(-scores,axis=1,kind='stable');top=scores[np.arange(n),order[:,0]]
    margin=top-scores[np.arange(n),order[:,1]];correct=order[:,0]==np.arange(n)
    best=None
    # Small validation-only pilot gate; not a calibrated correctness probability.
    for similarity in (0.,.2,.4,.6,.7,.8,.9,.95):
        for gap in (.01,.025,.05,.1,.15,.2):
            selected=(top>=similarity)&(margin>=gap); count=int(selected.sum())
            precision=float(correct[selected].mean()) if count else 0
            if count>=3 and precision>=.8:
                key=(count,precision,similarity,gap)
                if best is None or key>best[0]: best=(key,similarity,gap,count,precision)
    if best is None:
        return {'minimumSimilarity':1.0,'minimumMargin':2.0,'calibration':{'enabled':False,'reason':'No validation gate reached 80% retrieval precision on at least 3 queries. All matches require review.','validationQueries':n}}
    return {'minimumSimilarity':best[1],'minimumMargin':best[2], 'calibration':{'enabled':True,'validationQueries':n,
            'selectedQueries':best[3],'selectedPrecision':round(best[4],6),'targetPrecision':.8,
            'warning':'Small benchmark validation gate; not a correctness probability or financial-domain validation.'}}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--epochs',type=int,default=250);ap.add_argument('--seed',type=int,default=431)
    ap.add_argument('--dataset',type=Path,default=ROOT/'evaluation/corpora/cobol-javatrans/COBOL-JavaTrans.jsonl')
    args=ap.parse_args();started=time.time()
    raw=args.dataset.read_bytes();rows=[json.loads(x) for x in raw.decode().splitlines() if x.strip()]
    manifest=json.loads((ROOT/'evaluation/paired-code/dataset-manifest.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256'] or len(rows)!=143: raise ValueError('Pinned dataset hash/size mismatch')
    graphs=([build_graph(r['COBOL_canonical_solution'],'cobol') for r in rows], [build_graph(r['Java_canonical_solution'],'java') for r in rows])
    if any(g.stats['operations']<1 for gs in graphs for g in gs): raise ValueError('Insufficient graph extraction: inspect rather than silently excluding records')
    split,groups,links=split_tasks(rows,args.seed)
    metadata={'seed':args.seed,'method':'whole original tasks; transitive Java normalised 5-token-shingle Jaccard >=0.80 groups',
              'splits':{k:[rows[i]['task_id'] for i in ids] for k,ids in split.items()},
              'groups':[[rows[i]['task_id'] for i in group] for group in groups], 'nearDuplicateLinks':links}
    (ROOT/'evaluation/paired-code/task-splits.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps({'splits':{k:len(v) for k,v in split.items()},'groups':len(groups),'graphNodes':sum(len(g.x) for gs in graphs for g in gs)}),flush=True)
    params,epoch,history=fit(graphs,split,args.seed,args.epochs,True)
    # Same capacity/seed/training budget and val selection, without message passing.
    noparams,noepoch,nohistory=fit(graphs,split,args.seed,args.epochs,False)
    valscores=evaluate(rows,graphs,split['validation'],params)
    gate=thresholds(valscores)
    # Final test evaluation follows epoch/gate freeze. Earlier correctness-review runs
    # were observed; see the explicit audit note below. No hyperparameters were tuned.
    evaluations={}
    for name,indices in split.items():
        learned=evaluate(rows,graphs,indices,params)
        no=evaluate(rows,graphs,indices,noparams,False)
        cf=np.stack([graphs[0][i].x.mean(axis=0) for i in indices]);jf=np.stack([graphs[1][i].x.mean(axis=0) for i in indices])
        cf/=np.maximum(np.linalg.norm(cf,axis=1,keepdims=True),1e-9);jf/=np.maximum(np.linalg.norm(jf,axis=1,keepdims=True),1e-9)
        cn=[name_tokens(rows[i]['COBOL_canonical_solution'],'cobol') for i in indices]
        jn=[name_tokens(rows[i]['Java_canonical_solution'],'java') for i in indices]
        names=np.asarray([[len(a&b)/max(1,len(a|b)) for b in jn] for a in cn])
        evaluations[name]={'gnn':metrics(learned),'noMessagePassing':metrics(no),'semanticHistogram':metrics(cf@jf.T),'nameMatching':metrics(names)}
    model={'id':'paired-program-gnn-v1','architecture':'2-layer relation-aware GNN; tanh; mean pools both layers; learned readout; cosine retrieval',
           'featureNames':list(FEATURE_NAMES),'relations':list(RELATIONS),
           'weights':{k:v.round(12).tolist() for k,v in params.items()},
           'training':{'dataset':'COBOL-JavaTrans (143 original source pairs)','datasetSha256':manifest['sha256'],'sourceCommit':manifest['commit'],
                       'seed':args.seed,'epochsBudget':args.epochs,'selectedEpoch':epoch,'noMessageSelectedEpoch':noepoch,
                       'objective':'symmetric paired-source InfoNCE; temperature0.12; Adam0.004; weight decay0.0001',
                       'splitCounts':{k:len(v) for k,v in split.items()},'nearDuplicateGroups':len(groups),'selection':'validation MRR, then validation loss; never test',
                       'featureLeakageControls':['identifier spelling excluded','comments excluded','program/method/task names excluded','original-task grouped split before training']},
           'thresholds':gate,'evaluation':{'status':'BENCHMARK_PILOT','test':evaluations['test'],'validation':evaluations['validation'],
                       'financialDomainValidated':False,'scope':'whole-program paired-task retrieval, not statement localization or formal equivalence'},
           'limitations':['143 small HumanEval-derived pairs, not banking migrations','Pair labels are upstream correspondence, not independent correctness proofs',
                          'Heuristic graph extraction, not full compiler AST/CFG','Names excluded from model; name baseline may be stronger on named benchmark',
                          'Cosine scores are not calibrated probabilities','No financial-domain generalization claim','No defect prediction or code generation'],
           'provenance':{'dataset':manifest,'trainedOn':datetime.now(timezone.utc).date().isoformat(),'generatedBy':'AI-assisted implementation; actual CPU fitting on pinned paired source'}}
    MODEL_PATH.parent.mkdir(exist_ok=True)
    temporary=MODEL_PATH.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(model,separators=(',',':'))+'\n')
    temporary.replace(MODEL_PATH)
    report={'modelId':model['id'],'modelSha256':hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),'training':model['training'],
            'evaluation':evaluations,'thresholds':gate,'history':history,'noMessageHistory':nohistory,
            'durationSeconds':round(time.time()-started,3),'limitations':model['limitations'],
            'baselineConclusion':'Read measured metrics; message passing is not assumed superior.',
            'testExposureAudit':{'previousRunObserved':True,'previousRunGnnTop1':0.137931,'previousRunNoMessageTop1':0.344828,
               'reasonForRetrain':'Review found declared method names and string contents could become operation features. Fixed those leaks; added previously specified numeric width/precision/scale/signedness. Same split, seed, architecture size, objective, optimizer, epochs and selection protocol.',
               'limitation':'This test split has been observed during correctness review; treat final results as pilot evidence, not a pristine independent confirmatory study. No test-driven hyperparameter search was performed.'}}
    report_path=ROOT/'evaluation/paired-code/training-report.json'
    report_temporary=report_path.with_suffix('.json.tmp')
    report_temporary.write_text(json.dumps(report,indent=2)+'\n')
    report_temporary.replace(report_path)
    print(json.dumps({'evaluation':evaluations,'thresholds':gate,'selectedEpoch':epoch,'durationSeconds':report['durationSeconds']}),flush=True)

if __name__=='__main__': main()
