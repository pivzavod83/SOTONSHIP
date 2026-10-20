"""Strict bounded COBOL frontend for source-derived review graphs.

Supports the pilot's free/fixed scalar programs, numeric DISPLAY pictures,
arithmetic statements, IF/ELSE and inline PERFORM UNTIL. COMPLETE describes
extraction coverage, never execution, compilation or formal equivalence.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal,InvalidOperation
from fractions import Fraction
import re

from .semantic_ir import IRBuilder,NumericType,ProgramIR,SourceSpan

MAX_SOURCE_BYTES=200_000
MAX_LINES=4_000
MAX_STATEMENTS=2_000


@dataclass
class LogicalStatement:
    text: str
    span: SourceSpan


class ParseError(ValueError):
    pass


TOKEN=re.compile(r'\s*(?:([A-Za-z][A-Za-z0-9_-]*)|(\d+(?:\.\d+)?)|("(?:[^"]|"")*"|\'(?:[^\']|\'\')*\')|(\*\*|<=|>=|<>|!=|[()+\-*/=,<>&]))')
START=re.compile(r"^(?:ACCEPT|DISPLAY|COMPUTE|MOVE|ADD|SUBTRACT|MULTIPLY|DIVIDE|IF|ELSE|END-IF|PERFORM|END-PERFORM|STOP|GOBACK|CALL|COPY|EXEC|EVALUATE|END-EVALUATE|CONTINUE|EXIT|GO|STRING|UNSTRING|INSPECT|INITIALIZE|SET|READ|WRITE|OPEN|CLOSE)\b",re.I)


def tokenize(text: str) -> list[str]:
    result=[];position=0
    while position<len(text):
        if not text[position:].strip():break
        match=TOKEN.match(text,position)
        if not match:raise ParseError(f"Unsupported expression token near {text[position:position+24]!r}")
        result.append(next(g for g in match.groups() if g is not None));position=match.end()
    return result


def _strip_comment(text: str) -> str:
    # COBOL comments and literal quote escaping; *> inside a literal is data.
    quote=None;i=0
    while i<len(text):
        if quote:
            if text[i]==quote:
                if i+1<len(text) and text[i+1]==quote:i+=2;continue
                quote=None
        elif text[i] in "\"'":quote=text[i]
        elif text[i:i+2]=="*>":return text[:i]
        i+=1
    return text


def _picture(text: str) -> NumericType:
    picture=text.upper()
    if any(not 1<=int(repeat)<=256 for repeat in re.findall(r"\((\d+)\)",picture)):
        raise ParseError("PIC repetition must be within 1..256")
    if re.fullmatch(r"X(?:\(\d+\))?|X+",picture):
        return NumericType("alphanumeric",attrs={"picture":picture,"storage":"display_text"},picture=picture)
    if re.fullmatch(r"S?9(?:\(\d+\))?(?:9(?:\(\d+\))?)*(?:V9(?:\(\d+\))?(?:9(?:\(\d+\))?)*)?",picture):
        whole,_,fraction=picture.lstrip("S").partition("V")
        count=lambda p:sum(int(m.group(1) or 1) for m in re.finditer(r"9(?:\((\d+)\))?",p))
        integer_digits,scale=count(whole),count(fraction)
        if integer_digits+scale>38:raise ParseError("Numeric pictures above 38 digits are outside the bounded subset")
        return NumericType("decimal" if scale else "integer",precision=integer_digits+scale,scale=scale,signed=picture.startswith("S"),picture=picture,
                           attrs={"integer_digits":integer_digits,"storage":"cobol_pic_decimal","storage_radix":10})
    digits=r"(?:9(?:\(\d+\))?)+"
    edited=r"(?:(?:-(?:\(\d+\))?)+|(?:\+(?:\(\d+\))?)+|(?:Z(?:\(\d+\))?)+)"+digits+r"(?:\."+digits+r")?|"+digits+r"\."+digits
    if re.fullmatch(edited,picture):
        return NumericType("edited",picture=picture,attrs={"storage":"numeric_edited_display","format_picture":picture,
                                                               "format_observation":"textual_output","editing":"floating_sign" if "-" in picture or "+" in picture else "zero_suppression" if "Z" in picture else "fixed_decimal"})
    raise ParseError(f"Unsupported PIC {picture!r}")


class ExpressionParser:
    def __init__(self,tokens: list[str],builder: IRBuilder,span: SourceSpan):
        self.tokens=tokens;self.builder=builder;self.span=span;self.position=0;self.depth=0

    def peek(self):return self.tokens[self.position].upper() if self.position<len(self.tokens) else None
    def pop(self):
        if self.position>=len(self.tokens):raise ParseError("Incomplete expression")
        value=self.tokens[self.position];self.position+=1;return value
    def expect(self,value):
        if self.pop().upper()!=value:raise ParseError(f"Expected {value}")

    def expression(self,minimum=0) -> str:
        self.depth+=1
        try:
            if self.depth>64:raise ParseError("Expression nesting exceeds 64")
            return self._expression(minimum)
        finally:self.depth-=1

    def _expression(self,minimum=0) -> str:
        token=self.pop();upper=token.upper();b=self.builder
        if upper in ("+","-","NOT"):
            value=self.expression(60)
            typ=b.node(value).numeric_type
            if typ is not None and ((upper=="NOT" and typ.kind!="boolean") or (upper!="NOT" and typ.kind not in {"integer","decimal"})):
                raise ParseError("Unary operator has an incompatible operand type")
            node=value if upper=="+" else b.add_node("negate" if upper=="-" else "not",self.span,[value],numeric_type=b.node(value).numeric_type)
        elif token=="(":
            node=self.expression();self.expect(")")
        elif upper=="FUNCTION":
            function=self.pop().upper()
            if function not in {"ABS","MOD","REM","NUMVAL","TRIM","INTEGER","MIN","MAX"}:
                raise ParseError(f"Unsupported FUNCTION {function}")
            self.expect("(");args=[]
            while self.peek()!=")":
                args.append(self.expression())
                if self.peek()==",":self.pop()
                elif self.peek()!=")" and function not in {"MIN","MAX","MOD","REM"}:raise ParseError("Unexpected function argument")
            self.expect(")")
            arity=2 if function in {"MOD","REM"} else 1 if function not in {"MIN","MAX"} else None
            if (arity is not None and len(args)!=arity) or not args:raise ParseError(f"Wrong argument count for FUNCTION {function}")
            kinds=[b.node(arg).numeric_type.kind if b.node(arg).numeric_type else None for arg in args]
            if function in {"ABS","MOD","REM","INTEGER","MIN","MAX"} and any(kind not in {"integer","decimal",None} for kind in kinds):
                raise ParseError(f"FUNCTION {function} requires numeric operands")
            if function=="NUMVAL" and any(kind not in {"alphanumeric",None} for kind in kinds):
                raise ParseError("FUNCTION NUMVAL requires alphanumeric input in this subset")
            if function=="TRIM" and any(kind not in {"alphanumeric","edited",None} for kind in kinds):
                raise ParseError("FUNCTION TRIM requires textual or edited input")
            op={"ABS":"absolute","MOD":"modulo","REM":"modulo","NUMVAL":"convert","TRIM":"format","INTEGER":"floor","MIN":"minimum","MAX":"maximum"}[function]
            typ=NumericType("alphanumeric") if function=="TRIM" else NumericType("decimal",signed=True)
            attrs={"cobol_function":function}
            if function in {"MOD","REM"}:attrs["remainder_sign"]="divisor" if function=="MOD" else "dividend"
            if function=="NUMVAL":attrs.update({"conversion":"COBOL_NUMVAL","decimal_point":".","input_validation":"runtime_not_executed"})
            node=b.add_node(op,self.span,args,attrs,typ)
        elif re.fullmatch(r"\d+(?:\.\d+)?",token):
            decimal=Decimal(token);fraction=Fraction(decimal)
            node=b.add_node("literal",self.span,attrs={"value":format(decimal,"f"),"literal_kind":"decimal" if "." in token else "integer","exact_numerator":str(fraction.numerator),"exact_denominator":str(fraction.denominator),"lexical_scale":max(0,-decimal.as_tuple().exponent)},numeric_type=NumericType("decimal" if "." in token else "integer",scale=max(0,-decimal.as_tuple().exponent),signed=False))
        elif token[:1] in {"'",'"'}:
            node=b.add_node("literal",self.span,attrs={"value":token[1:-1].replace(token[0]*2,token[0]),"literal_kind":"string"},numeric_type=NumericType("alphanumeric"))
        elif upper in {"ZERO","ZEROS","ZEROES"}:
            node=b.add_node("literal",self.span,attrs={"value":"0","literal_kind":"integer","exact_numerator":"0","exact_denominator":"1"},numeric_type=NumericType("integer",scale=0,signed=False))
        elif re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*",token):
            node=b.read(upper,self.span)
        else:raise ParseError(f"Unsupported expression operand {token!r}")
        operators={"OR":(10,"or"),"AND":(20,"and"),"=":(30,"compare"),"!=":(30,"compare"),"<>":(30,"compare"),"<":(30,"compare"),">":(30,"compare"),"<=":(30,"compare"),">=":(30,"compare"),"+":(40,"add"),"-":(40,"subtract"),"*":(50,"multiply"),"/":(50,"divide"),"**":(70,"power")}
        while self.peek() in operators and operators[self.peek()][0]>=minimum:
            operator=self.pop().upper();precedence,op=operators[operator]
            right=self.expression(precedence if operator=="**" else precedence+1)
            kinds=[b.node(value).numeric_type.kind if b.node(value).numeric_type else None for value in (node,right)]
            if op in {"and","or"} and any(kind not in {"boolean",None} for kind in kinds):raise ParseError("Boolean operators require boolean operands")
            if op not in {"compare","and","or"} and any(kind not in {"integer","decimal",None} for kind in kinds):raise ParseError(f"Non-numeric operand in {op}")
            if op=="compare" and any(kind in {"alphanumeric","edited"} for kind in kinds):raise ParseError("Textual comparisons are outside the numeric subset")
            typ=NumericType("boolean") if op in {"compare","and","or"} else NumericType("decimal",signed=True)
            node=b.add_node(op,self.span,[node,right],{"operator":operator,"arithmetic":"COBOL_EXPRESSION"},typ)
        return node

    def finish(self) -> str:
        node=self.expression()
        if self.position!=len(self.tokens):raise ParseError(f"Unsupported trailing tokens: {' '.join(self.tokens[self.position:])}")
        return node


class CobolFrontend:
    def __init__(self,source: str,source_format: str):
        self.builder=IRBuilder(source,"cobol",source_format)
        self.statements=[];self.consumed=set();self.input_index=0;self.output_index=0

    def expr(self,text: str,span: SourceSpan) -> str:
        # A small, explicit normalisation for written COBOL relational phrases.
        text=re.sub(r"\bIS\s+NOT\s+EQUAL\s+TO\b","<>",text,flags=re.I)
        text=re.sub(r"\b(?:IS\s+)?GREATER\s+THAN\b",">",text,flags=re.I)
        text=re.sub(r"\b(?:IS\s+)?LESS\s+THAN\b","<",text,flags=re.I)
        text=re.sub(r"\b(?:IS\s+)?EQUAL\s+TO\b","=",text,flags=re.I)
        return ExpressionParser(tokenize(text),self.builder,span).finish()

    def receivers(self,text: str) -> list[tuple[str,bool]]:
        tokens=tokenize(text);result=[];i=0
        while i<len(tokens):
            name=tokens[i].upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9_-]*",name) or name=="ROUNDED":raise ParseError("Invalid receiving target")
            rounded=i+1<len(tokens) and tokens[i+1].upper()=="ROUNDED"
            result.append((name,rounded));i+=2 if rounded else 1
        if not result:raise ParseError("Missing receiving target")
        return result

    def operands(self,text: str,span: SourceSpan) -> list[str]:
        parser=ExpressionParser(tokenize(text),self.builder,span);values=[]
        while parser.position<len(parser.tokens):
            values.append(parser.expression())
            if parser.peek()==",":parser.pop()
        if not values:raise ParseError("Missing arithmetic operand")
        return values

    def sum_values(self,values: list[str],span: SourceSpan) -> str:
        self.require_numeric(values)
        result=values[0]
        for value in values[1:]:result=self.numeric_node("add",span,[result,value])
        return result

    def require_numeric(self,values: list[str]) -> None:
        if any(self.builder.node(value).numeric_type is None or self.builder.node(value).numeric_type.kind not in {"integer","decimal"} for value in values):
            raise ParseError("Arithmetic statement requires known numeric operands")

    def numeric_node(self,op: str,span: SourceSpan,values: list[str],attrs: dict | None = None) -> str:
        self.require_numeric(values)
        return self.builder.add_node(op,span,values,attrs,numeric_type=NumericType("decimal",signed=True))

    def store(self,name: str,value: str,span: SourceSpan,rounded=False):
        symbol=self.builder.program.symbols.get(name)
        value_type=self.builder.node(value).numeric_type
        if symbol and symbol["numericType"]["kind"] in {"integer","decimal"} and value_type is not None and value_type.kind not in {"integer","decimal"}:
            raise ParseError("Implicit alphanumeric/numeric receiving conversion is outside the subset")
        if symbol and symbol["numericType"]["kind"]=="edited":
            typ=NumericType(**symbol["numericType"])
            value=self.builder.add_node("format",span,[value],{"format_picture":typ.picture,"format":"COBOL_NUMERIC_EDITED"},typ)
        return self.builder.store(name,value,span,rounded)

    def prepare(self):
        b=self.builder;source=b.source;fmt=b.program.source_format
        if fmt not in {"FREE","FIXED"}:
            b.issue("SOURCE_FORMAT","source_format must be FREE or FIXED",SourceSpan(1,1));return
        if len(source.encode())>MAX_SOURCE_BYTES or len(source.split("\n"))>MAX_LINES:
            b.issue("SOURCE_BUDGET","Source exceeds the bounded extraction budget",SourceSpan(1,1));return
        procedure=False;pending=None
        def flush():
            nonlocal pending
            if pending:self.statements.append(pending);pending=None
        for number,raw in enumerate(source.split("\n"),1):
            line=raw.rstrip("\r");column=1
            if fmt=="FIXED":
                indicator=line[6:7]
                if indicator in {"*","/"}:continue
                if indicator.upper()=="D":b.issue("DEBUG_LINE","Fixed-format debug-line execution is outside the subset",SourceSpan(number,number,7));continue
                if indicator not in {""," ","-"}:b.issue("FIXED_INDICATOR","Unsupported fixed-format indicator",SourceSpan(number,number,7));continue
                if indicator=="-":b.issue("FIXED_CONTINUATION_UNSUPPORTED","Fixed-format indicator continuations require a compiler lexer and are outside this subset",SourceSpan(number,number,7))
                line=line[7:72];column=8
            text=_strip_comment(line).strip()
            if not text:continue
            column+=len(line)-len(line.lstrip())
            span=SourceSpan(number,number,column)
            if text.upper().startswith(">>SOURCE FORMAT"):
                requested=text.upper().split()[-1].rstrip(".")
                if requested!=fmt:b.issue("SOURCE_FORMAT_SWITCH","In-source format switches are outside the fixed-format profile",span)
                continue
            if re.match(r"PROCEDURE\s+DIVISION\s*\.\s*$",text,re.I):procedure=True;continue
            if not procedure:
                if re.fullmatch(r"(?:IDENTIFICATION|ID|DATA)\s+DIVISION\.|WORKING-STORAGE\s+SECTION\.|PROGRAM-ID\.\s+[\w-]+\.",text,re.I):continue
                declaration=re.fullmatch(r"(?:01|77)\s+([\w-]+)\s+PIC(?:TURE)?\s+(\S+?)(?:\s+(?:USAGE\s+(?:IS\s+)?)?(COMP-3|PACKED-DECIMAL|DISPLAY))?(?:\s+VALUE\s+(.+?))?\.?",text,re.I)
                if declaration:
                    name,picture,usage,initial=declaration.groups();picture=picture.rstrip(".")
                    try:
                        typ=_picture(picture)
                        if usage and usage.upper() in {"COMP-3","PACKED-DECIMAL"}:
                            if typ.kind not in {"integer","decimal"}:raise ParseError("Packed decimal needs a numeric unedited PIC")
                            typ=NumericType(typ.kind,typ.precision,typ.scale,typ.signed,picture=typ.picture,attrs={**typ.attrs,"storage":"packed_decimal","usage":usage.upper()})
                        b.declare(name.upper(),typ,span,{"initialization":"EXPLICIT_VALUE" if initial else "UNSPECIFIED","compiler_profile":"GnuCOBOL_3_2_scalar_display"})
                        if initial:self.store(name.upper(),self.expr(initial.rstrip("."),span),span)
                    except (ParseError,InvalidOperation) as exc:b.issue("DECLARATION_UNSUPPORTED",str(exc),span)
                else:b.issue("DECLARATION_OR_HEADER_UNSUPPORTED",f"Unsupported declaration or header: {text}",span)
                continue
            if text==".":continue
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*\.",text) and not START.match(text):
                flush();self.statements.append(LogicalStatement("@PARAGRAPH "+text[:-1].upper(),span));continue
            text=text[:-1] if text.endswith(".") else text
            if START.match(text):
                flush();pending=LogicalStatement(text,span)
            elif pending:
                pending.text+=" "+text;pending.span=SourceSpan(pending.span.start_line,number,pending.span.start_column)
            else:pending=LogicalStatement(text,span)
        flush()
        if not procedure:b.issue("MISSING_PROCEDURE","Missing supported PROCEDURE DIVISION header",SourceSpan(1,max(1,len(source.split("\n")))))
        if len(self.statements)>MAX_STATEMENTS:b.issue("STATEMENT_BUDGET","Too many logical statements",SourceSpan(1,len(source.split("\n"))));self.statements=[]

    def simple(self,statement: LogicalStatement,nested=False,has_following=False):
        text,span=statement.text,statement.span;b=self.builder;upper=text.upper()
        if upper.startswith("@PARAGRAPH "):
            b.add_node("structure",span,attrs={"paragraph_label":upper.split()[1],"fallthrough_only":True});return
        if upper in {"STOP RUN","GOBACK"}:
            if nested or has_following:raise ParseError("Early or nested termination requires terminal-path analysis outside this subset")
            b.add_node("stop",span,attrs={"kind":upper});return
        if re.match(r"ACCEPT\b",upper):
            targets=self.receivers(re.sub(r"^ACCEPT\s+","",text,flags=re.I))
            if len(targets)!=1 or targets[0][1]:raise ParseError("Only scalar ACCEPT is supported")
            target=targets[0][0];typ=b.program.symbols.get(target,{}).get("numericType")
            node=b.add_node("input",span,attrs={"input_index":self.input_index,"source":"stdin"},numeric_type=NumericType(**typ) if typ else None)
            self.input_index+=1;self.store(target,node,span);return
        if re.match(r"DISPLAY\b",upper):
            values=self.operands(re.sub(r"^DISPLAY\s+","",text,flags=re.I),span)
            b.add_node("output",span,values,{"output_index":self.output_index,"destination":"stdout","concatenated_operands":len(values),"newline":True});self.output_index+=1;return
        match=re.fullmatch(r"COMPUTE\s+(.+?)\s*=\s*(.+)",text,re.I)
        if match:
            receivers,expression=match.groups();targets=self.receivers(receivers);value=self.expr(expression,span)
            for name,rounded in targets:self.store(name,value,span,rounded)
            return
        match=re.fullmatch(r"MOVE\s+(.+?)\s+TO\s+(.+)",text,re.I)
        if match:
            expression,receivers=match.groups();targets=self.receivers(receivers)
            if any(r for _,r in targets):raise ParseError("MOVE ROUNDED is not a supported COBOL form")
            value=self.expr(expression,span)
            for name,_ in targets:self.store(name,value,span)
            return
        match=re.fullmatch(r"(ADD|SUBTRACT)\s+(.+?)\s+(TO|FROM)\s+(.+)",text,re.I)
        if match:
            verb,operands,direction,tail=match.groups();verb=verb.upper()
            if (verb,direction.upper()) not in {("ADD","TO"),("SUBTRACT","FROM")}:raise ParseError("Invalid arithmetic direction")
            giving=re.split(r"\s+GIVING\s+",tail,flags=re.I)
            if len(giving)>2:raise ParseError("Multiple GIVING clauses")
            total=self.sum_values(self.operands(operands,span),span)
            if len(giving)==2:
                base=self.expr(giving[0],span);value=self.numeric_node("add" if verb=="ADD" else "subtract",span,[base,total])
                for name,rounded in self.receivers(giving[1]):self.store(name,value,span,rounded)
            else:
                for name,rounded in self.receivers(tail):
                    base=b.read(name,span);value=self.numeric_node("add" if verb=="ADD" else "subtract",span,[base,total]);self.store(name,value,span,rounded)
            return
        match=re.fullmatch(r"MULTIPLY\s+(.+?)\s+BY\s+(.+)",text,re.I)
        if match:
            left=self.expr(match[1],span);self.require_numeric([left]);giving=re.split(r"\s+GIVING\s+",match[2],flags=re.I)
            if len(giving)==2:
                right=self.expr(giving[0],span);value=self.numeric_node("multiply",span,[left,right])
                for name,rounded in self.receivers(giving[1]):self.store(name,value,span,rounded)
            elif len(giving)==1:
                for name,rounded in self.receivers(giving[0]):self.store(name,self.numeric_node("multiply",span,[left,b.read(name,span)]),span,rounded)
            else:raise ParseError("Multiple GIVING clauses")
            return
        match=re.fullmatch(r"DIVIDE\s+(.+?)\s+(INTO|BY)\s+(.+)",text,re.I)
        if match:
            left=self.expr(match[1],span);self.require_numeric([left]);direction=match[2].upper();giving=re.split(r"\s+GIVING\s+",match[3],flags=re.I)
            if len(giving)==2:
                right=self.expr(giving[0],span);dividend,divisor=(right,left) if direction=="INTO" else (left,right)
                remainder=re.split(r"\s+REMAINDER\s+",giving[1],flags=re.I)
                targets=self.receivers(remainder[0]);value=self.numeric_node("divide",span,[dividend,divisor],{"division":"COBOL_DIVIDE","zero_divisor":"runtime_not_executed"})
                for name,rounded in targets:self.store(name,value,span,rounded)
                if len(remainder)==2:
                    if len(targets)!=1 or targets[0][1]:raise ParseError("REMAINDER supports one unrounded integer quotient target")
                    qtype=b.program.symbols.get(targets[0][0],{}).get("numericType",{})
                    if qtype.get("scale")!=0:raise ParseError("REMAINDER with fractional quotient storage is outside the subset")
                    rem_targets=self.receivers(remainder[1])
                    if len(rem_targets)!=1 or rem_targets[0][1]:raise ParseError("REMAINDER needs one target")
                    rem=self.numeric_node("modulo",span,[dividend,divisor],{"remainder_sign":"dividend","division":"COBOL_DIVIDE_REMAINDER","quotient_rounding":"TRUNCATE_TOWARD_ZERO"})
                    self.store(rem_targets[0][0],rem,span)
                elif len(remainder)>2:raise ParseError("Multiple REMAINDER clauses")
            elif len(giving)==1 and direction=="INTO":
                for name,rounded in self.receivers(giving[0]):self.store(name,self.numeric_node("divide",span,[b.read(name,span),left],{"division":"COBOL_DIVIDE"}),span,rounded)
            else:raise ParseError("DIVIDE BY requires GIVING")
            return
        raise ParseError(f"Unsupported computational statement: {text}")

    def block(self,index=0,terminators=(),depth=0):
        b=self.builder
        if depth>64:
            b.issue("CONTROL_NESTING","Control nesting exceeds 64",self.statements[index].span if index<len(self.statements) else SourceSpan(1,1));return index,None
        while index<len(self.statements):
            statement=self.statements[index];text=statement.text;upper=text.upper();span=statement.span
            if upper in terminators:return index,upper
            try:
                if upper.startswith("IF "):
                    condition=text[3:].strip()
                    if condition.upper().endswith(" THEN"):condition=condition[:-5].strip()
                    value=self.expr(condition,span)
                    if b.node(value).numeric_type is not None and b.node(value).numeric_type.kind!="boolean":raise ParseError("IF needs a supported boolean condition")
                    branch=b.add_node("branch",span,[value],{"condition":"COBOL_IF"},NumericType("boolean"));before=b.snapshot()
                    guard=b.add_node("guard",span,[value],{"expected":True,"branch":branch},NumericType("boolean"));b.active_controls.append(guard)
                    after_true,terminator=self.block(index+1,("ELSE","END-IF"),depth+1);b.active_controls.pop();true_state=b.snapshot();false_state=before
                    self.consumed.add(index)
                    if terminator=="ELSE":
                        self.consumed.add(after_true);b.restore(before)
                        guard=b.add_node("guard",self.statements[after_true].span,[value],{"expected":False,"branch":branch},NumericType("boolean"));b.active_controls.append(guard)
                        end,terminator=self.block(after_true+1,("END-IF",),depth+1);b.active_controls.pop();false_state=b.snapshot()
                    else:end=after_true
                    if terminator!="END-IF":b.issue("MISSING_END_IF","IF requires explicit END-IF",span);return end,None
                    self.consumed.add(end);b.merge([true_state,false_state],SourceSpan(span.start_line,self.statements[end].span.end_line));index=end+1;continue
                if upper.startswith("PERFORM UNTIL "):
                    header,phis=b.begin_loop(span,{"test_position":"BEFORE","continue_when_condition":False,"kind":"PERFORM_UNTIL"})
                    value=self.expr(text[len("PERFORM UNTIL "):],span)
                    if b.node(value).numeric_type is not None and b.node(value).numeric_type.kind!="boolean":raise ParseError("UNTIL needs a supported boolean condition")
                    b.node(header).inputs.append(value);b.edge(value,header,"control",{"role":"exit_condition"})
                    guard=b.add_node("guard",span,[value],{"expected":False,"loop":header},NumericType("boolean"));b.active_controls.append(guard)
                    end,terminator=self.block(index+1,("END-PERFORM",),depth+1);b.active_controls.pop();self.consumed.add(index)
                    if terminator!="END-PERFORM":b.issue("MISSING_END_PERFORM","PERFORM UNTIL requires END-PERFORM",span);return end,None
                    self.consumed.add(end);b.end_loop(header,phis,SourceSpan(span.start_line,self.statements[end].span.end_line));index=end+1;continue
                self.simple(statement,nested=depth>0,has_following=index<len(self.statements)-1);self.consumed.add(index)
            except (ParseError,InvalidOperation,IndexError) as exc:
                b.issue("STATEMENT_UNSUPPORTED",str(exc),span)
            index+=1
        return index,None

    def run(self) -> ProgramIR:
        self.prepare()
        if self.statements:self.block()
        b=self.builder
        b.program.attrs.update({"compiler_profile":"GnuCOBOL_3_2_scalar_DISPLAY_subset","extraction_only":True,
                                "coverage":{"logical_statements":len(self.statements),"consumed_statements":len(self.consumed),
                                            "unconsumed_statements":len(self.statements)-len(self.consumed)},
                                "input_count":self.input_index,"output_count":self.output_index,
                                "limitations":["COMPLETE means supported syntax was represented; it is not a compiler, execution result, or equivalence proof.","Unsupported dialect, storage or statement forms generate issues."]})
        return b.program


def extract_cobol(source: str, source_format: str = "FREE") -> ProgramIR:
    if not isinstance(source,str):raise ValueError("COBOL source must be a string")
    frontend=CobolFrontend(source,source_format.upper())
    try:return frontend.run()
    except ValueError as exc:
        frontend.builder.issue("EXTRACTION_BUDGET_OR_PARSE",str(exc),SourceSpan(1,max(1,len(source.split("\n")))))
        return frontend.builder.program
