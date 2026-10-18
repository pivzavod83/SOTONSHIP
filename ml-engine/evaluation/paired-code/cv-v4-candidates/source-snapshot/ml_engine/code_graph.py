"""Bounded, heuristic cross-language program graphs for learned retrieval, not proof.

Names establish local def/use topology only: no identifier spelling, comments,
program names, task IDs, or language labels enter the numeric representation.
This is intentionally separate from the verifier's supported arithmetic parser.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import numpy as np

OPS = ('add','subtract','multiply','divide','modulo','power','compare','and','or','not',
       'assign','branch','loop','return','call','absolute','length','index','slice',
       'append','sort','reverse','convert','minimum','maximum','sqrt','round','input','output')
TYPES = ('integer','decimal','float','string','boolean','collection')
FEATURE_NAMES = ('variable','operation','literal', *('op_'+x for x in OPS),
                 *('type_'+x for x in TYPES), 'constant_zero','constant_one','constant_two',
                 'constant_negative','constant_magnitude','string_literal','string_length','numeric_width','numeric_precision','numeric_scale','numeric_signed')
RELATIONS = ('data','control','sequence')
KEYWORDS = set(('identification division program id environment configuration section source computer object '
 'input output file control select assign organization access mode data working storage linkage local '
 'procedure using pic picture value values occurs times indexed by comp comp-1 comp-2 comp-3 binary '
 'usage display packed decimal sign leading trailing separate character global external redefines '
 'renames filler signed unsigned just justified blank when zero zeros zeroes space spaces high low '
 'move to compute add subtract from giving multiply divide into remainder rounded on size error '
 'end compute perform varying until with test before after thru through end perform if else end if '
 'evaluate when other end evaluate then continue stop run goback exit program end program '
 'accept display initialize string unstring inspect tallying replacing concatenate function '
 'and or not equal greater less than is are set true false search all end search '
 'import java util lang math public private protected static final class interface package extends '
 'implements new void int long double float short byte char boolean string list arraylist arrays '
 'integer character collections map hashmap set hashset null return if else for while do switch '
 'case break continue try catch throw throws this super system out println print length size '
 'get set add append toarray tostring parseint parsedouble valueof abs min max sqrt pow floor ceil '
 'substring charat contains equals split trim sort reverse indexof replace startswith endswith '
 'boolean result main solution').split())
TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:-[A-Za-z_0-9]+)*|\d+(?:\.\d+)?|==|!=|<=|>=|\+\+|--|&&|\|\||[+*/%<>=!\-]|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")

@dataclass
class CodeGraph:
    x: np.ndarray
    edges: dict[str, np.ndarray]
    stats: dict


def _feature(kind: str, operation: str | None = None, types=(), literal=None, numeric=None) -> np.ndarray:
    x = np.zeros(len(FEATURE_NAMES), dtype=np.float64)
    x[FEATURE_NAMES.index(kind)] = 1
    if operation:
        x[FEATURE_NAMES.index('op_'+operation)] = 1
    for name in types:
        x[FEATURE_NAMES.index('type_'+name)] = 1
    if numeric:
        for name,value in numeric.items(): x[FEATURE_NAMES.index(name)] = value
    if literal is not None:
        if literal.startswith(('"', "'")):
            x[FEATURE_NAMES.index('string_literal')] = 1
            x[FEATURE_NAMES.index('string_length')] = min(len(literal)-2, 100)/100
        else:
            value = float(literal)
            for test, name in ((value == 0,'constant_zero'),(value == 1,'constant_one'),
                               (value == 2,'constant_two'),(value < 0,'constant_negative')):
                x[FEATURE_NAMES.index(name)] = int(test)
            x[FEATURE_NAMES.index('constant_magnitude')] = min(np.log1p(abs(value)),10)/10
    return x


def clean_source(source: str, language: str, source_format: str = 'AUTO') -> str:
    if language == 'java':
        # Preserve literals while removing both comment forms.
        return re.sub(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|/\*.*?\*/|//[^\n]*',
                      lambda m: m.group(1) or '\n' * m.group().count('\n'), source, flags=re.S)
    lines=[]
    for line in source.splitlines():
        fixed = source_format == 'FIXED' or (source_format == 'AUTO' and len(line)>6 and
                   (line[:6].strip().isdigit() or (line[:6] == '      ' and line[6] in ' */-')))
        if fixed:
            if line[6:7] in ('*','/'):
                continue
            line=line[7:72]
        lines.append(re.split(r'\*>',line,maxsplit=1)[0])
    return '\n'.join(lines)


def build_graph(source: str, language: str, source_format: str = 'AUTO') -> CodeGraph:
    if language not in ('cobol','java'):
        raise ValueError('language must be cobol or java')
    text = clean_source(source,language,source_format)
    nodes=[]; variables={}; edges={r:[] for r in RELATIONS}; previous=None; controls=[]
    operational_lines=0
    def node(feature):
        if len(nodes)>=16000: raise ValueError('program graph exceeds node budget')
        nodes.append(feature); return len(nodes)-1
    def link(relation, left, right):
        if left != right:
            edges[relation].extend(((left,right),(right,left)))
    for raw in text.splitlines():
        line=raw.strip(); lower=line.lower()
        if not line or (language=='java' and re.match(r'(?:import|package)\b',lower)):
            continue
        if language=='cobol' and re.match(r'(?:identification|environment|data|working-storage|linkage|procedure|program-id|end program)\b',lower):
            continue
        # Paragraph/method declarations are labels, not semantic identifiers.
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*\.',line):
            continue
        # Declaration labels and literal contents never become operation features.
        if language=='java':
            line=re.sub(r'((?:public|private|protected)\s+(?:static\s+)?[\w<>\[\], ?]+\s+)\w+(?=\s*\()',r'\1 METHOD',line)
        if language=='java':
            # Package-private declarations have a return type but no access modifier.
            # Require a declaration/statement boundary and reject expression/control
            # keywords so `return helper(...)` and `new Type(...)` stay expressions.
            line=re.sub(
                r'((?:^|[{};])\s*(?:(?:static|final|synchronized|native|abstract|strictfp)\s+)*'
                r'(?!(?:return|throw|new|case|if|else|while|for|switch|catch|assert)\b)'
                r'[A-Za-z_$][\w$]*(?:\s*<[^{};()]+>)?(?:\s*\[\s*\])*\s+)'
                r'[A-Za-z_$][\w$]*(?=\s*\()', r'\1 METHOD',line)
        tokens=TOKEN.findall(line); low=[t.lower() for t in tokens]
        lower=re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', ' LITERAL ',line).lower()
        if language=='java':
            lower=re.sub(r'\b(?:this|super)\s*\.\s*[a-z_$][\w$]*(?=\s*\()', 'local_call',lower)
        if not tokens: continue
        types=[]
        if re.search(r'\b(?:int|long|short|byte|integer)\b',lower) or (language=='cobol' and re.search(r'\bpic(?:ture)?\s+s?9',lower)):
            types.append('integer')
        if re.search(r'\b(?:bigdecimal|decimal|comp-3)\b|\bpic(?:ture)?\s+[^\n]*v',lower): types.append('decimal')
        if re.search(r'\b(?:double|float|comp-1|comp-2)\b',lower): types.append('float')
        if re.search(r'\b(?:string|char|character)\b|\bpic(?:ture)?\s+x',lower): types.append('string')
        if re.search(r'\bboolean\b',lower): types.append('boolean')
        if re.search(r'\b(?:list|arraylist|occurs|map|set|hashmap|hashset)\b|\[\]',lower): types.append('collection')
        numeric={}
        if language=='java':
            widths={'byte':8,'short':16,'int':32,'integer':32,'long':64,'float':32,'double':64}
            present=[width for typ,width in widths.items() if re.search(r'\b'+typ+r'\b',lower)]
            if present:
                numeric={'numeric_width':max(present)/128,'numeric_signed':1.0}
        else:
            picture=re.search(r'\bpic(?:ture)?\s+(s?[9x](?:\(\d+\))?(?:v9(?:\(\d+\))?)?)',lower)
            if picture and '9' in picture.group(1):
                whole,_,fraction=picture.group(1).lstrip('s').partition('v')
                def digits(part):
                    count=re.search(r'\((\d+)\)',part)
                    return int(count.group(1)) if count else part.count('9')
                precision=digits(whole)+digits(fraction);scale=digits(fraction)
                numeric={'numeric_precision':min(precision,38)/38,'numeric_scale':min(scale,18)/18,
                         'numeric_signed':float(picture.group(1).startswith('s'))}
        # Strip declared method/class names; parameter variables remain available.
        identifiers=[]
        java_keywords=set(('import package public private protected static final class interface extends implements new void int long double float short byte char boolean string list arraylist arrays integer character collections map hashmap set hashset null return if else for while do switch case break continue try catch throw throws this super true false method').split())
        for k,t in enumerate(low):
            if not re.fullmatch(r'[a-z_][a-z_0-9]*(?:-[a-z_0-9]+)*',t) or t in (KEYWORDS if language=='cobol' else java_keywords): continue
            if language=='java' and ((k and low[k-1] in ('class','interface')) or re.search(r'\b'+re.escape(tokens[k])+r'\s*\(',line)): continue
            if language=='cobol' and re.search(r'\bperform\s+'+re.escape(t)+r'\b',lower) and 'varying' not in low: continue
            identifiers.append(t)
        varids=[]
        for identifier in dict.fromkeys(identifiers):
            if identifier not in variables: variables[identifier]=node(_feature('variable',types=types,numeric=numeric))
            elif types:
                for typ in types: nodes[variables[identifier]][FEATURE_NAMES.index('type_'+typ)]=1
                for name,value in numeric.items(): nodes[variables[identifier]][FEATURE_NAMES.index(name)]=value
            varids.append(variables[identifier])
        ops=[]
        def has(pattern, op):
            if re.search(pattern,lower): ops.append(op)
        if language=='cobol':
            has(r'\badd\b|\+','add'); has(r'\bsubtract\b|(?<![a-z_0-9])-(?![a-z_])','subtract')
            has(r'\bmultiply\b|\*','multiply'); has(r'\bdivide\b|/','divide')
            has(r'\b(?:mod|remainder)\b|%','modulo'); has(r'\*\*','power')
            has(r'==|!=|<=|>=|<|>|\b(?:equal|greater|less)\b','compare')
            has(r'\band\b','and');has(r'\bor\b','or');has(r'\bnot\b','not')
            has(r'(?<![<>=!])=(?!=)|\b(?:move|initialize|compute|set)\b','assign')
            has(r'\b(?:if|else|evaluate|when)\b','branch');has(r'\b(?:until|perform)\b','loop')
            has(r'\b(?:goback|stop)\b','return');has(r'\bfunction\s+abs\b','absolute')
            has(r'\bfunction\s+length\b','length');has(r'\bstring\b','append')
            has(r'\bsort\b','sort');has(r'\bfunction\s+reverse\b','reverse')
            has(r'\bfunction\s+(?:integer|numval)\b','convert')
            has(r'\bfunction\s+min\b','minimum');has(r'\bfunction\s+max\b','maximum')
            has(r'\bfunction\s+sqrt\b','sqrt');has(r'\brounded\b','round')
            has(r'\baccept\b','input');has(r'\bdisplay\b','output')
        else:
            has(r'\+','add');has(r'-','subtract');has(r'\*','multiply');has(r'/','divide');has(r'%','modulo')
            has(r'\.pow\s*\(','power');has(r'==|!=|<=|>=|<|>','compare')
            has(r'&&','and');has(r'\|\|','or');has(r'!','not');has(r'(?<![<>=!])=(?!=)','assign')
            has(r'\b(?:if|else|switch|case)\b','branch');has(r'\b(?:for|while)\b','loop')
            has(r'\breturn\b','return');has(r'\.abs\s*\(','absolute')
            has(r'\.(?:length|size)\b','length');has(r'\.(?:charat|get)\s*\(|\[[^\]]+\]','index')
            has(r'\.substring\s*\(','slice');has(r'\.(?:add|append)\s*\(','append')
            has(r'\.sort\s*\(','sort');has(r'\.reverse\s*\(','reverse')
            has(r'\.(?:parseint|parsedouble|valueof|tostring)\s*\(','convert')
            has(r'\.min\s*\(','minimum');has(r'\.max\s*\(','maximum');has(r'\.sqrt\s*\(','sqrt')
            has(r'\.(?:round|floor|ceil)\s*\(','round');has(r'\.(?:println|print)\s*\(','output')
        if not ops: continue
        operational_lines += 1
        literal_ids=[]
        for ti,token in enumerate(tokens):
            if token[0].isdigit() and ti and tokens[ti-1]=='-': token='-'+token
            if token[0].isdigit() or (token.startswith('-') and token[1:2].isdigit()) or token.startswith(('"',"'")):
                literal_ids.append(node(_feature('literal',literal=token)))
        for op in dict.fromkeys(ops):
            current=node(_feature('operation',op,types,numeric=numeric))
            for variable in varids: link('data',variable,current)
            for literal in literal_ids: link('data',literal,current)
            if previous is not None: link('sequence',previous,current)
            if controls: link('control',controls[-1],current)
            if op in ('branch','loop'): controls.append(current)
            previous=current
        # Bounded lexical nesting approximation, explicitly not a full compiler CFG.
        if re.search(r'end-if|end-perform|end-evaluate|}',lower) and controls: controls.pop()
        if len(nodes)>16000: raise ValueError('program graph exceeds node budget')
    if not nodes: nodes=[_feature('variable')]
    arrays={r:np.asarray(sorted(set(e)),dtype=np.int64).reshape(-1,2) for r,e in edges.items()}
    return CodeGraph(np.asarray(nodes),arrays,{'nodes':len(nodes),'operations':sum(int(x[1]) for x in nodes),
            'operationalLines':operational_lines,'edges':sum(len(e) for e in arrays.values()),
            'extractor':'heuristic-semantic-graph-v1','limitations':'Approximate lexical def/use and control; not a complete language parser.'})
