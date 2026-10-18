"""Portable NumPy relation-aware GNN encoder, trained on actual paired source.

Two learned message-passing layers feed whole-program mean pooling and an L2
normalised embedding. Cosine similarity is a retrieval score, never probability.
"""
from __future__ import annotations
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
from .code_graph import CodeGraph, FEATURE_NAMES, RELATIONS, build_graph

MODEL_PATH = Path(__file__).parent/'models'/'paired_program_gnn_v2_cv.json'

@lru_cache(maxsize=2)
def load_model(model_path: str | Path | None = None) -> dict:
    """Load the active artifact, or an explicitly pinned historical checkpoint."""
    raw=(Path(model_path) if model_path is not None else MODEL_PATH).read_bytes()
    model=json.loads(raw)
    if model['featureNames'] != list(FEATURE_NAMES) or model['relations'] != list(RELATIONS):
        raise ValueError('paired graph model/extractor schema mismatch')
    expected=initialise()
    if set(model.get('weights',{}))!=set(expected): raise ValueError('invalid paired model weight keys')
    for name,reference in expected.items():
        values=np.asarray(model['weights'][name],dtype=float)
        if values.shape!=reference.shape or not np.all(np.isfinite(values)):
            raise ValueError('invalid paired model weight shape or nonfinite values')
    gate=model['thresholds']
    if not (-1<=gate['minimumSimilarity']<=1 and 0<=gate['minimumMargin']<=2):
        raise ValueError('invalid paired model thresholds')
    model['_artifactSha256']=hashlib.sha256(raw).hexdigest()
    return model


def model_metadata(model=None) -> dict:
    model=model or load_model()
    if '_artifactSha256' not in model: raise ValueError('metadata requires a loaded artifact snapshot')
    return {'id':model['id'],'sha256':model['_artifactSha256'],
            'trainingDataset':model['training']['dataset'], 'evaluation':model['evaluation'],
            'limitations':model['limitations']}


def batch_graphs(graphs: list[CodeGraph], message_passing=True):
    sizes=np.asarray([len(g.x) for g in graphs]); groups=np.repeat(np.arange(len(graphs)),sizes)
    offsets=np.r_[0,np.cumsum(sizes)]
    x=np.concatenate([g.x for g in graphs])
    edges={}
    for relation in RELATIONS:
        parts=[g.edges[relation]+offsets[i] for i,g in enumerate(graphs) if len(g.edges[relation])]
        e=np.concatenate(parts) if parts and message_passing else np.empty((0,2),dtype=np.int64)
        # Incoming relation-specific means keep graph size from dominating.
        weights=1/np.maximum(1,np.bincount(e[:,0],minlength=len(x)))[e[:,0]] if len(e) else np.empty(0)
        edges[relation]=(e,weights)
    return x,edges,groups,sizes


def aggregate(x,e,w):
    out=np.zeros_like(x)
    if len(e): np.add.at(out,e[:,0],x[e[:,1]]*w[:,None])
    return out


def aggregate_backward(g,e,w):
    out=np.zeros_like(g)
    if len(e): np.add.at(out,e[:,1],g[e[:,0]]*w[:,None])
    return out


def initialise(seed=431, hidden=24, output=24):
    rng=np.random.default_rng(seed); f=len(FEATURE_NAMES)
    params={}
    for layer,fanin in ((1,f),(2,hidden)):
        for relation in ('self',*RELATIONS):
            params[f'W{layer}_{relation}']=rng.normal(0,np.sqrt(1/(fanin*4)),(fanin,hidden))
        params[f'b{layer}']=np.zeros(hidden)
    params['readout']=rng.normal(0,np.sqrt(1/(hidden*2)),(hidden*2,output))
    return params


def forward(batch, params, need_cache=False):
    x,edges,groups,sizes=batch
    h=x; cache=[]
    pooled=[]
    for layer in (1,2):
        inputs={'self':h,**{r:aggregate(h,*edges[r]) for r in RELATIONS}}
        pre=sum(v@params[f'W{layer}_{r}'] for r,v in inputs.items())+params[f'b{layer}']
        h=np.tanh(pre)
        pool=np.zeros((len(sizes),h.shape[1])); np.add.at(pool,groups,h)
        pool/=sizes[:,None]; pooled.append(pool)
        cache.append((inputs,h))
    p=np.concatenate(pooled,axis=1); z=p@params['readout']
    norms=np.maximum(np.linalg.norm(z,axis=1,keepdims=True),1e-9); v=z/norms
    return (v,(cache,p,z,norms,batch)) if need_cache else v


def backward(grad, saved, params):
    cache,p,z,norms,batch=saved; x,edges,groups,sizes=batch
    v=z/norms; dz=(grad-v*np.sum(grad*v,axis=1,keepdims=True))/norms
    grads={'readout':p.T@dz}; dp=dz@params['readout'].T
    hidden=cache[0][1].shape[1]; dh=np.zeros_like(cache[1][1])
    for layer in (2,1):
        inputs,h=cache[layer-1]
        dh+=dp[:,(layer-1)*hidden:layer*hidden][groups]/sizes[groups,None]
        dpre=dh*(1-h*h); grads[f'b{layer}']=dpre.sum(axis=0)
        prev=np.zeros_like(inputs['self'])
        for r,values in inputs.items():
            grads[f'W{layer}_{r}']=values.T@dpre
            local=dpre@params[f'W{layer}_{r}'].T
            prev+=local if r=='self' else aggregate_backward(local,*edges[r])
        dh=prev
    return grads


def paired_loss(c,j,temperature=.12):
    logits=c@j.T/temperature; n=len(c)
    shifted=logits-logits.max(axis=1,keepdims=True)
    p=np.exp(shifted); p/=p.sum(axis=1,keepdims=True)
    shifted_t=logits-logits.max(axis=0,keepdims=True)
    q=np.exp(shifted_t); q/=q.sum(axis=0,keepdims=True)
    loss=float(-.5*np.mean(np.log(np.maximum(np.diag(p),1e-15))+np.log(np.maximum(np.diag(q),1e-15))))
    d=(p+q-2*np.eye(n))/(2*n*temperature)
    return loss,d@j,d.T@c


def encode_graph(graph: CodeGraph, model=None) -> np.ndarray:
    model=model or load_model()
    params={k:np.asarray(v,dtype=float) for k,v in model['weights'].items()}
    return forward(batch_graphs([graph]),params)[0]


def encode_source(source: str, language: str, source_format='AUTO', model=None) -> np.ndarray:
    return encode_graph(build_graph(source,language,source_format),model)
