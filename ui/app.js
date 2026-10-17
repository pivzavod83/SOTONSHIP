const STORAGE_KEY = "sotonship-comparison-demo-v2";

const defaults = {
  cobol: `       IDENTIFICATION DIVISION.\n       PROGRAM-ID. CALC-INTEREST.\n\n       DATA DIVISION.\n       WORKING-STORAGE SECTION.\n       01  WS-PRINCIPAL       PIC S9(9)V99 COMP-3.\n       01  WS-RATE            PIC S9(3)V9(4) COMP-3.\n       01  WS-PERIODS         PIC 9(3) COMP.\n       01  WS-INTEREST        PIC S9(9)V99 COMP-3.\n       01  WS-TOTAL           PIC S9(9)V99 COMP-3.\n       01  WS-IS-ELIGIBLE     PIC X.\n\n       PROCEDURE DIVISION.\n\n           COMPUTE WS-INTEREST = WS-PRINCIPAL * WS-RATE\n               ROUNDED.\n\n           IF WS-INTEREST > ZERO\n               MOVE 'Y' TO WS-IS-ELIGIBLE\n           ELSE\n               MOVE 'N' TO WS-IS-ELIGIBLE\n           END-IF.\n\n           COMPUTE WS-TOTAL = WS-PRINCIPAL + WS-INTEREST\n               ROUNDED.\n           GOBACK.`,
  java: `package com.acme.payments;\n\nimport java.math.BigDecimal;\nimport java.math.RoundingMode;\n\npublic class InterestCalculator {\n\n    public static Result calculate(\n            BigDecimal principal,\n            BigDecimal rate,\n            int periods) {\n\n        // Calculate interest\n        BigDecimal interest = principal.multiply(rate)\n                .setScale(2, RoundingMode.HALF_EVEN);\n\n        // Determine eligibility\n        String isEligible;\n        if (interest.compareTo(BigDecimal.ZERO) > 0) {\n            isEligible = "Y";\n        } else {\n            isEligible = "N";\n        }\n\n        // Calculate total\n        BigDecimal total = principal.add(interest)\n                .setScale(2, RoundingMode.HALF_EVEN);\n\n        return new Result(interest, total, isEligible);\n    }\n}`
};

const findings = [
  { id: 1, severity: "high", label: "High", location: "CALC-INTEREST.cbl:15", counterpart: "InterestCalculator.java:13", title: "Decimal precision may differ", detail: "COBOL uses COMP-3 with ROUNDED; Java applies HALF_EVEN after multiplication.", status: "OPEN", mapping: "precision" },
  { id: 2, severity: "medium", label: "Medium", location: "CALC-INTEREST.cbl:6", counterpart: "InterestCalculator.java:9", title: "Data type representation", detail: "Verify range, signedness and scaling between packed decimal and BigDecimal.", status: "OPEN", mapping: "types" },
  { id: 3, severity: "low", label: "Low", location: "CALC-INTEREST.cbl:18", counterpart: "InterestCalculator.java:18", title: "Conditional logic aligned", detail: "IF condition and outcomes appear equivalent.", status: "RESOLVED", mapping: "condition" }
];

const state = { view: "compare", filter: "all", queueVisible: true, running: false, reviewed: new Set() };
const editors = {};
let scrollLock = false;
const graphDetails = {
  interest: { title: "CALC-INTEREST", code: "COBOL ↔ calculate()", input: "principal, rate, periods", output: "interest amount", returns: "BigDecimal interest", confidence: 96, risk: "Packed-decimal rounding maps to Java BigDecimal. Review the highlighted relationship." },
  rate: { title: "APPLY-RATE", code: "COBOL ↔ applyRate()", input: "customer type", output: "selected rate", returns: "BigDecimal rate", confidence: 94, risk: "Customer-rate branches are aligned across both implementations." },
  eligibility: { title: "CHECK-ELIGIBILITY", code: "COBOL ↔ isEligible()", input: "interest > ZERO", output: "Y / N flag", returns: "boolean eligibility", confidence: 99, risk: "No high-attention mapping detected in this branch." },
  round: { title: "ROUND-INTEREST", code: "COBOL ↔ setScale()", input: "packed decimal interest", output: "2dp HALF-EVEN", returns: "rounded BigDecimal", confidence: 62, risk: "High attention: verify COMP-3 precision and Java rounding order." },
  total: { title: "CALC-TOTAL", code: "COBOL ↔ calculateTotal()", input: "principal + interest", output: "total amount", returns: "BigDecimal total", confidence: 91, risk: "The addition and final scale appear equivalent." },
  result: { title: "BUILD-RESULT", code: "COBOL ↔ Result(...) ", input: "interest, total, flag", output: "result fields", returns: "Result object", confidence: 97, risk: "Result field order is aligned." },
  write: { title: "WRITE-DETAIL", code: "COBOL ↔ save()", input: "Result object", output: "payment record", returns: "void", confidence: 95, risk: "Output mapping is aligned for the demo." }
};

function escapeHtml(text) { return text.replace(/[&<>]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[char])); }
function protect(source, regex, store, cls) { return source.replace(regex, value => { const token=`@@P${store.length}@@`; store.push(`<span class="${cls}">${value}</span>`); return token; }); }
function highlightLine(raw, language) {
  const stored=[]; let line=escapeHtml(raw);
  if(language==="java"){
    line=protect(line,/\/\/.*$/g,stored,"tok-comment");
    line=protect(line,/"[^"]*"/g,stored,"tok-string");
    line=line.replace(/\b(package|import|public|class|static|return|if|else|new|int)\b/g,'<span class="tok-key">$1</span>')
      .replace(/\b(BigDecimal|RoundingMode|String|Result|InterestCalculator)\b/g,'<span class="tok-type">$1</span>')
      .replace(/\b(\d+)\b/g,'<span class="tok-number">$1</span>');
  }else{
    line=protect(line,/'[^']*'/g,stored,"tok-string");
    line=line.replace(/\b(IDENTIFICATION|DIVISION|PROGRAM-ID|DATA|WORKING-STORAGE|SECTION|PROCEDURE|PIC|COMP-3|COMP|COMPUTE|ROUNDED|IF|ELSE|MOVE|TO|END-IF|GOBACK|ZERO)\b/g,'<span class="tok-key">$1</span>')
      .replace(/\b(WS-[A-Z-]+|CALC-INTEREST)\b/g,'<span class="tok-name">$1</span>')
      .replace(/\b(\d+)\b/g,'<span class="tok-number">$1</span>');
  }
  return line.replace(/@@P(\d+)@@/g,(_,n)=>stored[Number(n)]);
}
function lineClass(language,index){
  const line=index+1;
  if(language==="cobol"){
    if(line>=5&&line<=11)return "safe-line";
    if(line>=15&&line<=16)return "risk-line";
    if(line>=18&&line<=22)return "safe-line";
    if(line>=24&&line<=26)return "neutral-line";
  }else{
    if(line>=6&&line<=11)return "safe-line";
    if(line>=13&&line<=15)return "risk-line";
    if(line>=17&&line<=22)return "safe-line";
    if(line>=24&&line<=26)return "neutral-line";
  }
  return "";
}
function loadCode(language){ try{return JSON.parse(localStorage.getItem(STORAGE_KEY)||"{}")[language]||defaults[language]}catch{return defaults[language]} }
function saveCode(language,value){ if(!document.querySelector("#saveEdits")?.checked)return; let data={};try{data=JSON.parse(localStorage.getItem(STORAGE_KEY)||"{}")}catch{}data[language]=value;localStorage.setItem(STORAGE_KEY,JSON.stringify(data)); }

function createEditor(host,language){
  host.innerHTML="";
  const cm=CodeMirror(host,{
    value:loadCode(language),
    mode:language==="cobol"?"cobol":"text/x-java",
    theme:"sotonship",
    lineNumbers:true,
    lineWrapping:false,
    indentUnit:4,
    tabSize:4,
    indentWithTabs:false,
    smartIndent:true,
    electricChars:true,
    autoCloseBrackets:true,
    matchBrackets:true,
    viewportMargin:30,
    extraKeys:{
      Tab(editor){if(editor.somethingSelected())editor.indentSelection("add");else editor.replaceSelection("    ","end","+input")},
      "Shift-Tab":"indentLess",
      "Ctrl-S"(){saveCode(language,cm.getValue());showToast(`${language.toUpperCase()} changes saved locally`)},
      "Cmd-S"(){saveCode(language,cm.getValue());showToast(`${language.toUpperCase()} changes saved locally`)}
    }
  });
  const riskLine=language==="cobol"?14:12;
  function decorate(){
    cm.eachLine(handle=>cm.removeLineClass(handle,"background"));
    for(let i=0;i<cm.lineCount();i++){
      const cls=lineClass(language,i);
      if(cls==="safe-line")cm.addLineClass(i,"background","cm-safe-line");
      if(cls==="risk-line")cm.addLineClass(i,"background","cm-risk-line");
      if(cls==="neutral-line")cm.addLineClass(i,"background","cm-neutral-line");
    }
    if(!cm.getAllMarks().some(mark=>mark.__attentionMark)){
      const label=document.createElement("span");
      label.className="cm-inline-warning";
      label.innerHTML='<b>▲</b><strong>HIGH ATTENTION</strong><span>Decimal precision may differ</span>';
      const ch=cm.getLine(riskLine)?.length||0;
      const mark=cm.setBookmark({line:riskLine,ch},{widget:label,insertLeft:false});
      mark.__attentionMark=true;
    }
  }
  cm.on("change",()=>saveCode(language,cm.getValue()));
  cm.on("scroll",instance=>{if(scrollLock||!document.querySelector("#syncEditors").checked)return;const other=editors[language==="cobol"?"java":"cobol"]?.cm;if(!other)return;scrollLock=true;const info=instance.getScrollInfo();other.scrollTo(info.left,info.top);scrollLock=false});
  cm.on("focus",()=>host.classList.add("editor-focused"));
  cm.on("blur",()=>host.classList.remove("editor-focused"));
  const api={host,cm,render(){cm.refresh();decorate()},setValue(value){cm.setValue(value);decorate()},getValue(){return cm.getValue()}};
  editors[language]=api;
  decorate();
}

function renderFindings(){
  const shown=findings.filter(f=>state.filter==="all"||f.severity===state.filter);
  document.querySelector("#queueRows").innerHTML=shown.map(f=>`<div class="queue-row queue-data" role="row" data-finding="${f.id}"><span>${f.id}</span><span class="severity ${f.severity}"><i class="sev-dot ${f.severity}"></i>${f.label}</span><span class="location">${f.location}<i>↔</i>${f.counterpart}</span><span class="finding"><strong>${f.title}</strong><small>${f.detail}</small></span><button class="status ${f.status==='RESOLVED'||state.reviewed.has(f.id)?'resolved':''}" data-status="${f.id}">${state.reviewed.has(f.id)?'RESOLVED':f.status}</button><span class="actions"><button class="review-button" data-review="${f.id}">${f.status==='RESOLVED'?'View':'Review'}</button><button class="more-button" aria-label="More actions">⋯</button></span></div>`).join("");
}
function switchView(view){state.view=view;document.querySelectorAll(".view").forEach(v=>v.classList.toggle("active",v.id===`${view}View`));document.querySelectorAll(".nav-item").forEach(n=>n.classList.toggle("active",n.dataset.view===view));if(view==="compare")setTimeout(()=>Object.values(editors).forEach(e=>e.render()),0);if(view==="dependencies")setTimeout(syncDependencyEdges,0)}
function showToast(message){const t=document.querySelector("#toast");t.textContent=message;t.classList.add("show");clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>t.classList.remove("show"),2200)}
function focusMapping(mapping){
  const f=findings.find(item=>item.mapping===mapping);if(!f)return;switchView("compare");
  const line=mapping==="precision"?12:mapping==="types"?5:17;const cm=editors.java.cm;cm.focus();cm.setSelection({line,ch:0},{line,ch:cm.getLine(line).length});cm.scrollIntoView({line,ch:0},100);showToast(`${f.title} selected`);
}
function runVerification(){if(state.running)return;state.running=true;const b=document.querySelector("#runVerification");b.classList.add("running");b.textContent="Analyzing code…";setTimeout(()=>b.textContent="Checking equivalence…",750);setTimeout(()=>{state.running=false;b.classList.remove("running");b.innerHTML="<span>▶</span> Run verification";showToast("Verification complete · 1 counterexample found");switchView("evidence")},1700)}

document.addEventListener("click",event=>{
  const nav=event.target.closest("[data-view]");if(nav)return switchView(nav.dataset.view);
  const target=event.target.closest("[data-view-target]");if(target)return switchView(target.dataset.viewTarget);
  const filter=event.target.closest("[data-filter]");if(filter){state.filter=filter.dataset.filter;document.querySelectorAll(".filter").forEach(b=>b.classList.toggle("active",b===filter));renderFindings();return}
  const mapping=event.target.closest("[data-mapping]");if(mapping)return focusMapping(mapping.dataset.mapping);
  const review=event.target.closest("[data-review]");if(review)return focusMapping(findings.find(f=>f.id===Number(review.dataset.review)).mapping);
  const status=event.target.closest("[data-status]");if(status){const id=Number(status.dataset.status);state.reviewed.has(id)?state.reviewed.delete(id):state.reviewed.add(id);renderFindings();showToast(state.reviewed.has(id)?"Finding marked resolved":"Finding reopened");return}
  const close=event.target.closest("[data-close-modal]");if(close)document.querySelector("#settingsModal").hidden=true;
  const module=event.target.closest("[data-module]");if(module){const detail=graphDetails[module.dataset.module];document.querySelectorAll("[data-module]").forEach(n=>n.classList.toggle("active",n.dataset.module===module.dataset.module));if(detail){document.querySelector("#mappingTitle").textContent=detail.title;document.querySelector("#mappingCode").textContent=detail.code;document.querySelector("#mappingInputs").textContent=detail.input;document.querySelector("#mappingOutputs").textContent=detail.output;document.querySelector("#mappingReturns").textContent=detail.returns;document.querySelector("#mappingConfidence").textContent=`${detail.confidence}%`;document.querySelector("#mappingConfidenceBar").style.width=`${detail.confidence}%`;document.querySelector("#mappingRisk").textContent=detail.risk}showToast(`${detail?.title||"Function"} selected`)}
});
document.querySelector("#runVerification").addEventListener("click",runVerification);
document.querySelector("#layoutButton").addEventListener("click",()=>{state.queueVisible=!state.queueVisible;document.querySelector("#compareView").classList.toggle("queue-collapsed",!state.queueVisible);showToast(`${state.queueVisible?'Review queue shown':'Review queue hidden'}`)});
document.querySelector("#settingsButton").addEventListener("click",()=>document.querySelector("#settingsModal").hidden=false);
document.querySelector("#settingsModal").addEventListener("click",e=>{if(e.target.id==="settingsModal")e.currentTarget.hidden=true});
document.querySelector("#showSafe").addEventListener("change",e=>document.body.classList.toggle("hide-safe",!e.target.checked));
document.querySelector("#resetDemo").addEventListener("click",()=>{localStorage.removeItem(STORAGE_KEY);editors.cobol.setValue(defaults.cobol);editors.java.setValue(defaults.java);state.reviewed.clear();renderFindings();document.querySelector("#settingsModal").hidden=true;showToast("Demo reset")});
document.querySelector("#applyFix").addEventListener("click",()=>{const fixed=defaults.java.replace("BigDecimal interest = principal.multiply(rate)\n                .setScale(2, RoundingMode.HALF_EVEN);","BigDecimal interest = principal\n                .multiply(rate)\n                .setScale(2, RoundingMode.HALF_EVEN);");editors.java.setValue(fixed);saveCode("java",fixed);switchView("compare");showToast("Suggested fix applied to Java demo")});
document.querySelector("#exportEvidence").addEventListener("click",()=>{const blob=new Blob(["Sotonship demo verification evidence\nResult: Counterexample found\nCOBOL: £333.50\nJAVA: £333.49\nNo backend was used."],{type:"text/plain"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="sotonship-demo-evidence.txt";a.click();URL.revokeObjectURL(a.href);showToast("Evidence exported")});
document.querySelector("#fitGraph").addEventListener("click",()=>showToast("Dependency graph fitted to view"));
document.querySelector("#projectSwitcher").addEventListener("click",()=>showToast("payments-modernisation is the active demo project"));

createEditor(document.querySelector("#cobolEditor"),"cobol");
createEditor(document.querySelector("#javaEditor"),"java");
window.demoEditors=editors;
function syncDependencyEdges(){
  const canvas=document.querySelector(".classic-graph-canvas");
  if(!canvas)return;
  const svg=canvas.querySelector(".dependency-edges");
  if(!svg)return;
  const bounds=canvas.getBoundingClientRect();
  if(bounds.width<1||bounds.height<1)return;
  const sx=1000/bounds.width, sy=600/bounds.height;
  const box=key=>{
    const el=canvas.querySelector(`.node-${key}`), r=el.getBoundingClientRect();
    return {left:(r.left-bounds.left)*sx,right:(r.right-bounds.left)*sx,top:(r.top-bounds.top)*sy,bottom:(r.bottom-bounds.top)*sy,width:r.width*sx,height:r.height*sy,cx:(r.left+r.width/2-bounds.left)*sx,cy:(r.top+r.height/2-bounds.top)*sy};
  };
  const set=(name,d)=>{const edge=svg.querySelector(`[data-edge="${name}"]`);if(edge)edge.setAttribute("d",d)};
  const interest=box("interest"), rate=box("rate"), eligibility=box("eligibility"), round=box("round"), total=box("total"), result=box("result"), write=box("write");
  const bend=(a,b,offset=0)=>Math.round((a.right+b.left)/2+offset);
  set("interest-rate",`M ${interest.right} ${interest.top+interest.height*.34} H ${interest.right+18} V ${rate.cy} H ${rate.left}`);
  // Keep the high-attention route away from the eligibility route so their
  // shared source card never produces overlapping strokes or arrowheads.
  const attentionLaneY=Math.max(8,Math.min(rate.top,round.top)-10);
  const attentionLaneX=interest.right+9;
  const attentionTargetX=round.left-9;
  set("interest-round",`M ${interest.right} ${interest.cy} H ${attentionLaneX} V ${attentionLaneY} H ${attentionTargetX} V ${round.cy} H ${round.left}`);
  set("interest-eligibility",`M ${interest.right} ${interest.bottom-.34*interest.height} H ${interest.right+30} V ${eligibility.cy} H ${eligibility.left}`);
  set("rate-round",`M ${rate.right} ${rate.cy} H ${round.left-18} V ${round.cy} H ${round.left}`);
  set("rate-total",`M ${rate.right} ${rate.bottom-.28*rate.height} H ${bend(rate,total,-8)} V ${total.cy-.22*total.height} H ${total.left}`);
  set("eligibility-total",`M ${eligibility.right} ${eligibility.cy} H ${bend(eligibility,total,-8)} V ${total.cy+.2*total.height} H ${total.left}`);
  set("round-total",`M ${round.cx} ${round.bottom} V ${total.top}`);
  set("total-result",`M ${total.cx} ${total.bottom} V ${result.top}`);
  set("result-write",`M ${result.right} ${result.cy} H ${bend(result,write,0)} V ${write.cy} H ${write.left}`);
  const attentionEdge=svg.querySelector('[data-edge="interest-round"]');
  const callout=canvas.querySelector(".path-callout");
  if(attentionEdge&&callout){
    // Place the label on the clear horizontal run above the cards.
    callout.style.left=`${(attentionLaneX+attentionTargetX)/20}%`;
    callout.style.top=`${attentionLaneY/6}%`;
    callout.style.transform="translate(-50%,-50%)";
  }
}
window.addEventListener("resize",syncDependencyEdges);
requestAnimationFrame(syncDependencyEdges);
renderFindings();
