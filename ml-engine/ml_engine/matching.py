"""Source-bound whole-program GNN retrieval. Suggestions are never equivalence proof."""
from __future__ import annotations
import hashlib,json,re,sys
import numpy as np
from .code_graph import build_graph
from .paired_gnn import load_model,model_metadata,encode_graph

MAX_BYTES=2*1024*1024

def _source(value,name):
    if not isinstance(value,str) or not value.strip() or len(value)>100000 or len(value.splitlines())>1500 or '\0' in value:
        raise ValueError(f'{name} must be nonempty source, at most 100000 characters/1500 lines, without NUL')
    return value


def match_sources(request: dict) -> dict:
    if not isinstance(request,dict): raise ValueError('matching request must be an object')
    if len(json.dumps(request,ensure_ascii=False).encode())>MAX_BYTES: raise ValueError('matching request exceeds 2 MiB')
    cobol=_source(request.get('cobolSource'),'cobolSource')
    fmt=request.get('cobolSourceFormat','AUTO')
    if fmt not in ('AUTO','FREE','FIXED'): raise ValueError('cobolSourceFormat must be AUTO, FREE, or FIXED')
    candidates=request.get('candidates')
    if not isinstance(candidates,list) or not 1<=len(candidates)<=20: raise ValueError('provide 1 to 20 Java candidates')
    top=request.get('topK',5)
    if isinstance(top,bool) or not isinstance(top,int) or not 1<=top<=20: raise ValueError('topK must be an integer from 1 to 20')
    seen=set();validated=[]
    for candidate in candidates:
        if not isinstance(candidate,dict): raise ValueError('candidate must be an object')
        identifier=candidate.get('candidateId');name=candidate.get('moduleName')
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,80}',identifier) or identifier in seen:
            raise ValueError('candidateId must be unique and match [A-Za-z0-9._:-]{1,80}')
        if not isinstance(name,str) or not name.strip() or len(name)>160 or re.search(r'[/\\\x00-\x1f\x7f]',name):
            raise ValueError('moduleName must be nonempty, at most 160 characters, without paths or controls')
        java=_source(candidate.get('javaSource'),'javaSource');seen.add(identifier)
        validated.append((identifier,name,java))
    model=load_model();graph=build_graph(cobol,'cobol',fmt);vector=encode_graph(graph,model,language='cobol')
    ranked=[];feature_counts={}
    for identifier,name,java in validated:
        target=build_graph(java,'java');embedding=encode_graph(target,model,language='java')
        similarity=float(np.clip(vector@embedding,-1,1));feature_counts[identifier]=target.stats['operations']
        ranked.append({'candidateId':identifier,'moduleName':name,'javaSourceSha256':hashlib.sha256(java.encode()).hexdigest(),
                       'similarity':round(similarity,8)})
    ranked.sort(key=lambda c:(-c['similarity'],c['candidateId']))
    for index,item in enumerate(ranked,1): item['rank']=index
    gate=model['thresholds'];threshold={'minimumSimilarity':gate['minimumSimilarity'],'minimumMargin':gate['minimumMargin']}
    status='REVIEW_REQUIRED'
    if len(ranked)<2:
        reason='Only one candidate: no alternative exists to assess the retrieval margin. Review the correspondence manually.'
    elif graph.stats['operations']<3 or feature_counts[ranked[0]['candidateId']]<3:
        reason='Too little supported graph structure for a meaningful suggestion. Review the correspondence manually.'
    elif not gate['calibration']['enabled']:
        reason='Validation did not support a retrieval gate. Rankings are experimental and require manual review.'
    elif ranked[0]['similarity']<gate['minimumSimilarity'] or ranked[0]['similarity']-ranked[1]['similarity']<gate['minimumMargin']:
        reason='Top candidate falls below the validation similarity or margin gate; confirm correspondence manually. Scores are cosine similarities, not probabilities.'
    else:
        status='MATCH_SUGGESTED'
        reason='Top candidate meets a small benchmark validation gate; engineer confirmation is required. Financial-domain matching is unvalidated and similarity is not proof.'
    return {'status':status,'reason':reason,'matchingIsProof':False,'granularity':'PROGRAM',
            'model':model_metadata(model),'cobolSourceSha256':hashlib.sha256(cobol.encode()).hexdigest(),
            'candidates':ranked[:top],'thresholds':threshold}


def main():
    if sys.argv[1:] != ['--stdin']:
        print('usage: python -m ml_engine.matching --stdin',file=sys.stderr);return 2
    try:
        raw=sys.stdin.buffer.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES: raise ValueError('matching request exceeds 2 MiB')
        request=json.loads(raw.decode('utf-8'))
        result=match_sources(request)
        print(json.dumps(result,separators=(',',':'),allow_nan=False))
        return 0
    except (ValueError,TypeError,KeyError,UnicodeError) as error:
        # Error messages contain contract details, never submitted source text.
        print(json.dumps({'error':'INVALID_MATCHING_REQUEST','message':str(error)}),file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
