'use strict';

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { catalog: null, research: null, task: 'defect', metric: 'accuracy', assessment: 'default', view: 'overview', detail: null, trigger: null, toastTimer: null };
  const metricNames = { accuracy: 'Accuracy', precision: 'Precision', recall: 'Defect recall', f1: 'F1', top1: 'Top-1', mrr: 'MRR', hitAt1: 'Hit@1', hitAt3: 'Hit@3', reviewWorkload: 'Review workload', missedDefects: 'Missed defects' };
  const viewNames = { overview: 'Overview', versions: 'Model registry', 'case-study': 'Failure inspector', research: 'Research & next steps' };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const list = value => Array.isArray(value) ? value : value == null ? [] : [value];
  const text = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);
  const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const ratio = value => finite(value) ? Number(value) : null;
  const percent = value => finite(value) ? `${(Number(value) * 100).toFixed(Number(value) === 1 || Number(value) === 0 ? 0 : 1)}%` : '—';
  const metricValue = (metrics, key) => key === 'missedDefects' ? finite(metrics?.[key]) ? String(metrics[key]) : '—' : key === 'mrr' ? finite(metrics?.[key]) ? Number(metrics[key]).toFixed(3) : '—' : percent(metrics?.[key]);
  const slug = value => String(value ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const safeUrl = value => {
    if (typeof value !== 'string' || !value.trim()) return null;
    try { const url = new URL(value, location.origin); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
  };
  const link = (url, label, className = '', extra = '') => { const safe = safeUrl(url); return safe ? `<a class="${escape(className)}" href="${escape(safe)}" target="_blank" rel="noopener" ${extra}>${escape(label)} <span aria-hidden="true">↗</span></a>` : ''; };
  const taskLabel = task => task === 'matching' ? 'PROGRAM MATCHING' : 'DEFECT DETECTION';
  const statusBadge = version => `<span class="status-badge ${escape(slug(version.status))}">${escape(String(version.status || 'recorded').toUpperCase())}</span>`;
  const getVersions = () => list(state.catalog?.versions);
  const getVersion = id => getVersions().find(version => version.id === id);
  const defaultAssessment = version => list(version.assessments).find(a => a.id === version.defaultAssessmentId) || list(version.assessments).find(a => /test|regression/i.test(`${a.id} ${a.label}`)) || list(version.assessments)[0] || null;
  const cohort = assessment => {
    const label = `${assessment?.id ?? ''} ${assessment?.label ?? ''} ${typeof assessment?.scope === 'string' ? assessment.scope : ''}`.toLowerCase();
    if (/cross|oof|out.of.fold|cv\b/.test(label)) return 'cv';
    if (/valid/.test(label)) return 'validation';
    if (/test|holdout|regression|shared.23/.test(label)) return 'test';
    if (/train/.test(label)) return 'training';
    return 'other';
  };
  const cohortNames = { default: 'Reported primary assessment', cv: 'Grouped cross-validation', validation: 'Validation', test: 'Test / regression reports', training: 'Training', other: 'Other reports' };
  const selectAssessment = version => state.assessment === 'default' ? defaultAssessment(version) : state.assessment === 'test' && version.task === 'matching' ? list(version.assessments).find(a => a.cohort === 'humaneval-shared-23') || list(version.assessments).find(a => cohort(a) === state.assessment) || null : list(version.assessments).find(a => cohort(a) === state.assessment) || null;
  const scopeText = assessment => typeof assessment?.scope === 'string' ? assessment.scope : assessment?.scope?.description || assessment?.scope?.name || '';
  const countLabel = assessment => finite(assessment?.counts?.queries) ? `${assessment.counts.queries} queries` : finite(assessment?.pairs) ? `${assessment.pairs} pairs` : finite(assessment?.samples) ? `${assessment.samples} samples` : 'n not reported';

  function toast(message) {
    $('#toast').textContent = message; $('#toast').hidden = false;
    clearTimeout(state.toastTimer); state.toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3800);
  }

  async function readJson(path) {
    const response = await fetch(path, { cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}. Start the benchmark server and retry.`);
    const value = await response.json();
    if (value?.error) throw new Error(text(value.error));
    return value;
  }

  async function load() {
    $('#loading').hidden = false; $('#error-panel').hidden = true; $('#content').hidden = true;
    try {
      const result = await Promise.allSettled([readJson('/api/catalog'), readJson('/api/research')]);
      if (result[0].status === 'rejected') throw result[0].reason;
      const catalog = result[0].value;
      if (!Array.isArray(catalog.versions)) throw new Error('The catalog did not contain a versions list. Check the catalog-generation report.');
      state.catalog = catalog;
      state.research = result[1].status === 'fulfilled' ? result[1].value : null;
      state.researchError = result[1].status === 'rejected' ? result[1].reason.message : null;
      renderRepository(); renderStats(); renderComparison(); renderRegistry(); renderCase(); renderResearch();
      $('#loading').hidden = true; $('#content').hidden = false;
      navigate(location.hash.slice(1));
    } catch (error) {
      $('#loading').hidden = true; $('#error-panel').hidden = false;
      $('#error-message').textContent = error.message || 'An unexpected catalog error occurred.';
    }
  }

  function renderRepository() {
    const repo = state.catalog.repository || {};
    $('#branch-name').textContent = repo.branch || 'Branch not recorded';
    const branch = safeUrl(repo.branchUrl); $('#branch-link').href = branch || '#';
    $('#branch-link').title = repo.branch ? `Exact GitHub branch: ${repo.branch}` : 'Repository branch unavailable';
    if (!branch) $('#branch-link').removeAttribute('href');
    const repoUrl = safeUrl(repo.url); if (repoUrl) $('#sidebar-repository').href = repoUrl; else $('#sidebar-repository').removeAttribute('href');
    const commitUrl = safeUrl(repo.commitUrl); if (commitUrl) $('#footer-commit').href = commitUrl; else $('#footer-commit').removeAttribute('href');
    $('#footer-commit').textContent = repo.commit ? `Revision ${repo.commit.slice(0, 8)} ↗` : 'Revision unavailable';
    $('#version-count').textContent = String(getVersions().length);
  }

  function renderStats() {
    const versions = getVersions();
    const defectVersions = versions.filter(v => v.task === 'defect');
    const experimental = [...defectVersions].reverse().find(v => v.status === 'experimental') || defectVersions.at(-1);
    const reference = experimental ? defaultAssessment(experimental) : null;
    const misses = reference?.counts?.fn ?? reference?.metrics?.missedDefects;
    const totalDefects = finite(reference?.counts?.tp) && finite(reference?.counts?.fn) ? Number(reference.counts.tp) + Number(reference.counts.fn) : null;
    const stats = [
      { label: 'RECORDED MODEL VERSIONS', value: versions.length, unit: '', note: `${defectVersions.length} defect · ${versions.filter(v => v.task === 'matching').length} matching` },
      { label: 'LATEST DEFECT RECALL', value: metricValue(reference?.metrics, 'recall'), unit: '', note: reference ? `${experimental.name} · ${countLabel(reference)}` : 'No defect assessment recorded', color: 'teal' },
      { label: 'DEFECTS STILL MISSED', value: finite(misses) ? misses : '—', unit: totalDefects === null ? '' : `/ ${totalDefects}`, note: reference?.reused ? 'Known regression examples · not fresh data' : 'Within the selected recorded assessment', color: 'amber' },
      { label: 'AUTONOMOUS ACCEPTANCES', value: '0', unit: '', note: 'ML prioritizes review; it never grants approval' }
    ];
    $('#overview-stats').innerHTML = stats.map(s => `<article class="stat"><div class="stat-label">${escape(s.label)}</div><div class="stat-value ${s.color || ''}">${escape(s.value)}<small>${escape(s.unit)}</small></div><p>${escape(s.note)}</p></article>`).join('');
    const contracts = state.catalog.contracts;
    $('#contract-summary').innerHTML = contracts ? `<span><strong>${escape(contracts.passed)} / ${escape(contracts.fixtureCount)} extractor contracts passed</strong> · ${escape(contracts.scope || 'Representation diagnostics, not model accuracy')}</span>${link(contracts.source?.reportUrl, 'Inspect diagnostics')}` : '';
  }

  function renderComparison() {
    const versions = getVersions().filter(v => v.task === state.task);
    const categories = [...new Set(versions.flatMap(v => list(v.assessments).map(cohort)))];
    if (state.assessment !== 'default' && !categories.includes(state.assessment)) state.assessment = 'default';
    $('#assessment-select').innerHTML = ['default', ...['cv', 'validation', 'test', 'training', 'other'].filter(c => categories.includes(c))].map(id => `<option value="${id}" ${state.assessment === id ? 'selected' : ''}>${cohortNames[id]}</option>`).join('');
    $$('.task-switch button').forEach(button => { const selected = button.dataset.task === state.task; button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected)); });
    const keys = state.task === 'matching' ? ['top1', 'mrr'] : ['accuracy', 'recall', 'precision', 'f1'];
    if (!keys.includes(state.metric)) state.metric = keys[0];
    $('#metric-switch').innerHTML = keys.map(key => `<button data-metric="${key}" class="${state.metric === key ? 'selected' : ''}" aria-pressed="${state.metric === key}">${metricNames[key]}</button>`).join('');
    const rows = versions.map(version => ({ version, assessment: selectAssessment(version) })).filter(row => row.assessment);
    const reused = rows.some(row => row.assessment.reused);
    $('#comparison-note').innerHTML = `${reused ? '<strong>Known or reused examples are included.</strong> ' : ''}Each row retains its own cohort, denominator, and evaluation protocol. This is an evidence comparison, not a pooled leaderboard. Missing results are shown as “—”.`;
    $('#chart-title').textContent = `${metricNames[state.metric]} by recorded version`;
    $('#chart-subtitle').textContent = state.task === 'defect' ? 'Defect is the positive class. More recall must be weighed against review workload.' : 'Retrieval quality measures counterpart matching, not translation correctness.';
    renderChart(rows);
    const columns = state.task === 'matching' ? ['top1', 'mrr'] : ['accuracy', 'recall', 'precision', 'f1'];
    $('#comparison-table thead').innerHTML = `<tr><th>Model / status</th><th>Assessment · cohort</th>${columns.map(key => `<th>${escape(metricNames[key])}</th>`).join('')}<th>${state.task === 'defect' ? 'Missed / defects' : 'Scope'}</th><th class="sr-only">Inspect</th></tr>`;
    $('#comparison-table tbody').innerHTML = rows.length ? rows.map(({ version: v, assessment: a }) => {
      const defects = finite(a.counts?.tp) && finite(a.counts?.fn) ? Number(a.counts.tp) + Number(a.counts.fn) : null;
      const missed = a.counts?.fn ?? a.metrics?.missedDefects;
      return `<tr class="model-row"><td><button data-open-version="${escape(v.id)}" class="model-name-button">${escape(v.name)} <small>↗</small></button><div style="margin-top:5px">${statusBadge(v)}</div></td><td><span>${escape(a.label || a.id)}</span><div class="source-small" style="margin-top:4px">${escape(countLabel(a))}${a.reused ? ' · REUSED' : ''}</div><div class="cohort-note">${escape(a.cohort || scopeText(a))}</div></td>${columns.map(key => `<td class="metric-cell ${state.metric === key ? 'emphasis' : ''}">${metricValue(a.metrics, key)}</td>`).join('')}<td class="metric-cell">${state.task === 'defect' ? finite(missed) ? `${escape(missed)} / ${defects ?? '?'}` : '—' : a.reused ? 'Known set' : 'See protocol'}</td><td><button class="icon-button" data-open-version="${escape(v.id)}" aria-label="Inspect ${escape(v.name)}">→</button></td></tr>`;
    }).join('') : '<tr><td colspan="8" class="empty-state">No versions report this assessment. Choose another assessment.</td></tr>';
  }

  function renderChart(rows) {
    if (!rows.length) { $('#comparison-chart').innerHTML = '<div class="empty-state">No results for this assessment.</div>'; return; }
    const width = 920, left = 183, right = 63, rowHeight = 41, top = 28, bottom = 28, height = top + bottom + rows.length * rowHeight;
    const plotWidth = width - left - right;
    const lines = [0, .25, .5, .75, 1].map(tick => `<line class="chart-grid" x1="${left + tick * plotWidth}" x2="${left + tick * plotWidth}" y1="${top - 7}" y2="${height - bottom + 4}"/><text class="chart-tick" x="${left + tick * plotWidth}" y="${height - 8}" text-anchor="middle">${state.metric === 'mrr' ? tick.toFixed(2) : `${Math.round(tick * 100)}%`}</text>`).join('');
    const bars = rows.map(({ version, assessment }, index) => {
      const y = top + index * rowHeight, value = ratio(assessment.metrics?.[state.metric]);
      const label = version.shortName || version.name;
      const short = label.length > 27 ? `${label.slice(0, 25)}…` : label;
      return `<g><title>${escape(`${version.name}: ${metricValue(assessment.metrics, state.metric)}; ${assessment.label}; ${countLabel(assessment)}${assessment.reused ? '; reused examples' : ''}`)}</title><text class="chart-label" x="${left - 14}" y="${y + 12}" text-anchor="end">${escape(short)}</text>${value === null ? `<text class="chart-na" x="${left + 7}" y="${y + 12}">NOT REPORTED</text>` : `<rect class="chart-bar ${escape(version.status)}" x="${left}" y="${y - 1}" width="${Math.max(0, Math.min(1, value)) * plotWidth}" height="18" rx="2"/><text class="chart-value" x="${left + Math.max(0, Math.min(1, value)) * plotWidth + 9}" y="${y + 12}">${escape(metricValue(assessment.metrics, state.metric))}</text>`}</g>`;
    }).join('');
    $('#comparison-chart').innerHTML = `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="chart-accessible-title chart-accessible-description"><title id="chart-accessible-title">${escape(metricNames[state.metric])} comparison</title><desc id="chart-accessible-description">Recorded version scores. Cohorts may differ. Exact figures, assessment names and sample counts are available in the table immediately below.</desc>${lines}${bars}</svg>`;
  }

  function renderRegistry() {
    const search = $('#version-search').value.trim().toLowerCase(), task = $('#registry-task').value, status = $('#registry-status').value;
    const versions = getVersions().filter(v => (task === 'all' || v.task === task) && (status === 'all' || v.status === status) && (!search || `${v.name} ${v.id} ${v.summary} ${list(v.changes).join(' ')} ${list(v.problems).join(' ')}`.toLowerCase().includes(search)));
    $('#registry-summary').textContent = `${versions.length} of ${getVersions().length} recorded versions${search ? ` matching “${search}”` : ''}`;
    $('#version-grid').innerHTML = versions.length ? versions.map((version, index) => {
      const a = defaultAssessment(version), keys = version.task === 'matching' ? ['top1', 'mrr'] : ['accuracy', 'recall'];
      return `<article class="version-card"><div class="version-card-top"><span class="version-number">${escape(version.id)}</span>${statusBadge(version)}</div><span class="task-tag">${taskLabel(version.task)}</span><h3 style="margin-top:8px">${escape(version.name)}</h3><p class="card-summary">${escape(version.summary)}</p><div class="mini-metrics">${keys.map(key => `<div><span>${escape(metricNames[key])}</span>${metricValue(a?.metrics, key)}</div>`).join('')}<span class="mini-assessment">${escape(a?.label || 'No assessment recorded')} · ${escape(a ? countLabel(a) : '—')}${a?.reused ? ' · reused' : ''}</span></div><p class="card-warning">${escape(list(version.problems)[0] || 'Review the report scope before interpreting this result.')}</p><div class="card-footer"><button class="detail-button" data-open-version="${escape(version.id)}">Inspect version <span aria-hidden="true">→</span></button>${link(version.source?.branchUrl, 'GitHub branch', 'source-small')}</div></article>`;
    }).join('') : '<div class="empty-state"><h3>No matching versions</h3><p>Try another task, status, or search term.</p><button class="secondary-button" data-reset-filters>Clear filters</button></div>';
  }

  function integrity(source) {
    const status = typeof source?.integrity === 'object' ? source.integrity.status || (source.integrity.valid === true ? 'verified' : source.integrity.valid === false ? 'mismatch' : '') : source?.integrity;
    const normalized = String(status || '').toLowerCase();
    const good = /verified|match|valid|pass|bound|ok/.test(normalized) && !/mismatch|unverified|invalid|not/.test(normalized);
    const bad = /mismatch|invalid|fail|missing/.test(normalized);
    return `<span class="${good ? 'integrity-pass' : bad ? 'integrity-fail' : 'integrity-neutral'}">${good ? '●' : bad ? '!' : '○'} ${escape(status || 'Integrity status not reported')}</span>`;
  }

  function sourceBlock(source, versionId) {
    if (!source) return '<p class="notice-line">No source binding was recorded.</p>';
    const checks = list(source.checks), passed = checks.filter(check => check.verified === true).length;
    return `<div class="source-links">${link(source.branchUrl, 'Exact GitHub branch')}${link(source.commitUrl, 'Immutable commit')}${link(source.localReportUrl || (versionId ? `/reports/${encodeURIComponent(versionId)}` : null), 'Open raw report')}${link(source.reportUrl, 'Report on GitHub')}</div><div class="binding">${integrity(source)}${source.integrity === 'unverified' ? ' · Computed report hash; no independent prior hash for this report.' : ''}<br>REPORT ${escape(source.reportPath || 'Not recorded')}<br>SHA-256 ${escape(source.sha256 || 'Not recorded')}<br>${escape(source.integrityScope || 'Hash binding checks concern artifact identity, not semantic correctness or statistical validity.')}${checks.length ? `<details style="margin-top:9px"><summary>${passed} / ${checks.length} related artifact bindings verified · inspect checks</summary><ul class="evidence-checks">${checks.map(check => `<li><span>${check.verified === true ? '✓' : check.verified === false ? '!' : '○'}</span>${escape(check.path || text(check))}</li>`).join('')}</ul></details>` : ''}</div>`;
  }

  function openDetail(id, trigger) {
    const version = getVersion(id); if (!version) return;
    state.detail = id; state.trigger = trigger || document.activeElement;
    const assessments = list(version.assessments);
    $('#version-detail').innerHTML = `<div class="detail-close-row"><span class="eyebrow">VERSION RECORD / ${escape(version.id)}</span><button class="icon-button" data-close-detail aria-label="Close version details">×</button></div><span class="task-tag">${taskLabel(version.task)}</span><h2 id="detail-title">${escape(version.name)}</h2>${statusBadge(version)}<p class="detail-summary" style="margin-top:17px">${escape(version.summary)}</p>${['changes', 'problems', 'nextSteps'].map(key => `<section class="detail-section"><h3>${{ changes: 'Method & changes', problems: 'Known problems / suggested explanations', nextSteps: 'Next steps' }[key]}</h3>${list(version[key]).length ? `<ul>${list(version[key]).map(item => `<li>${escape(text(item))}</li>`).join('')}</ul>` : '<p class="notice-line">Not recorded in this version.</p>'}</section>`).join('')}<section class="detail-section"><h3>Recorded assessments</h3><p class="detail-summary">Read each cohort and protocol separately. No model score grants autonomous acceptance.</p>${assessments.map(a => `<article class="detail-assessment"><h3>${escape(a.label || a.id)}</h3><p>${escape(countLabel(a))}${a.reused ? ' · KNOWN / REUSED EXAMPLES' : ''}<br>${escape(scopeText(a))}</p><div class="detail-metrics">${Object.keys(metricNames).filter(key => finite(a.metrics?.[key])).map(key => `<div><span>${escape(metricNames[key])}</span>${metricValue(a.metrics, key)}</div>`).join('') || '<p>No classifier metrics reported.</p>'}</div>${a.counts && Object.keys(a.counts).some(k => finite(a.counts[k])) ? `<div class="confusion">${['tp', 'tn', 'fp', 'fn'].filter(key => finite(a.counts[key])).map(key => `<span>${key.toUpperCase()} ${escape(a.counts[key])}</span>`).join('')}</div>` : ''}${a.source?.reportUrl ? `<p style="margin-top:13px;margin-bottom:0">${link(a.source.localReportUrl || a.source.reportUrl, 'Assessment report', 'text-link')}</p>` : ''}</article>`).join('')}</section><section class="detail-section"><h3>Exact artifact source</h3>${sourceBlock(version.source, version.id)}</section>`;
    $('#detail-overlay').hidden = false; document.body.style.overflow = 'hidden'; $('#version-detail').focus();
  }

  function closeDetail() {
    $('#detail-overlay').hidden = true; document.body.style.overflow = ''; state.detail = null;
    if (state.trigger?.isConnected) state.trigger.focus();
  }

  function highlight(line, language) {
    // Tokenize raw source before escaping: source content is never inserted as HTML.
    const pattern = /("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\/\/.*$|\*>.*$|\b\d+(?:\.\d+)?[LlFfDd]?\b|\b[A-Za-z_][A-Za-z_0-9-]*\b)/g;
    const javaKeywords = new Set('public private protected static final class interface return new if else while for do switch case break continue throw throws import package null true false try catch this'.split(' '));
    const javaTypes = new Set('BigDecimal RoundingMode Scanner String int long double float boolean void Integer Long Math System'.split(' '));
    const cobolKeywords = new Set('IDENTIFICATION DIVISION PROGRAM-ID ENVIRONMENT DATA WORKING-STORAGE SECTION PROCEDURE PIC PICTURE VALUE COMPUTE MOVE TO GIVING REMAINDER DIVIDE BY INTO MULTIPLY ADD SUBTRACT FROM IF ELSE END-IF PERFORM UNTIL END-PERFORM DISPLAY ACCEPT STOP RUN ROUNDED FUNCTION END-COMPUTE END-DIVIDE ON SIZE ERROR END-ADD END-SUBTRACT END-MULTIPLY CONTINUE AND OR NOT EQUAL GREATER LESS THAN IS'.split(' '));
    let output = '', previous = 0, match;
    while ((match = pattern.exec(line))) {
      output += escape(line.slice(previous, match.index));
      const token = match[0], upper = token.toUpperCase(); let type = '';
      if (/^\/\/|^\*>/.test(token)) type = 'comment';
      else if (/^["']/.test(token)) type = 'string';
      else if (/^\d/.test(token)) type = 'number';
      else if (language === 'java' && javaKeywords.has(token) || language === 'cobol' && cobolKeywords.has(upper)) type = 'keyword';
      else if (language === 'java' && javaTypes.has(token) || language === 'cobol' && ['NUMVAL', 'MOD', 'ABS', 'TRIM', 'MAX', 'MIN'].includes(upper)) type = 'type';
      output += type ? `<span class="tok-${type}">${escape(token)}</span>` : escape(token);
      previous = pattern.lastIndex;
    }
    return output + escape(line.slice(previous));
  }

  function renderCode(code, language, culprit) {
    const lines = String(code || '').split(/\r?\n/);
    return `<div class="code-panel"><div class="code-heading"><h3>${language === 'cobol' ? 'COBOL / original' : 'JAVA / candidate'}</h3><span>${lines.length} LINES</span></div><pre class="code-lines" aria-label="${language === 'cobol' ? 'Original COBOL source' : 'Candidate Java source with defect highlighted'}"><code>${lines.map((line, index) => {
      const number = index + 1, marked = culprit?.language === language && number >= culprit.startLine && number <= (culprit.endLine || culprit.startLine);
      return `<span class="code-line ${marked ? 'marked' : ''}" ${marked ? 'aria-label="Flagged defect line"' : ''}><span class="line-number" aria-hidden="true">${number}</span><span class="code-text">${highlight(line, language) || ' '}</span></span>`;
    }).join('')}</code></pre>${culprit?.language === language ? `<div class="line-explanation"><strong>LINE ${escape(culprit.startLine)}${culprit.endLine && culprit.endLine !== culprit.startLine ? `–${escape(culprit.endLine)}` : ''}</strong><span>${escape(culprit.reason)}</span></div>` : ''}</div>`;
  }

  function renderCase() {
    const item = state.catalog.caseStudy;
    if (!item) { $('#case-content').innerHTML = '<div class="empty-state"><h3>No case evidence is available</h3><p>A source-bound discrepancy case has not been recorded in this catalog.</p></div>'; return; }
    const witness = item.witness || {}, evidence = item.evidence || {};
    const inputText = typeof witness.inputs === 'string' ? witness.inputs : JSON.stringify(witness.inputs, null, 2);
    const outputText = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? 'Not recorded';
    $('#case-content').innerHTML = `<article class="case-summary"><div><h2>${escape(item.title)}</h2><p>${escape(item.summary)}</p><div class="case-source-note">${escape(item.datasetKind || 'Dataset provenance not recorded')} · Behavior-backed example; not a real customer incident.</div></div><span class="case-id">${escape(item.id)}</span></article><div class="witness-grid"><div class="witness-cell"><span class="eyebrow">WITNESS / INPUTS</span><pre>${escape(inputText || 'Not recorded')}</pre><small>Stored counterexample input</small></div><div class="witness-cell"><span class="eyebrow">COBOL OUTPUT</span><pre>${escape(outputText(witness.cobolOutput ?? witness.expectedOutput))}</pre><small>Reference behavior for these inputs</small></div><div class="witness-cell different"><span class="eyebrow">JAVA OUTPUT / MISMATCH</span><pre>${escape(outputText(witness.javaOutput))}</pre><small>Different behavior in the recorded evidence</small></div></div><div class="code-grid">${renderCode(item.cobolCode, 'cobol', item.culprit)}${renderCode(item.javaCode, 'java', item.culprit)}</div><article class="case-note"><h3>What this evidence establishes</h3><p>${escape(witness.explanation || 'The stored input produces different recorded outputs. This demonstrates a defect for that input; it does not establish coverage of all possible inputs.')}</p><p><strong>Stored evidence, not a live execution.</strong> This inspector reads the existing sources and discrepancy report. The marker identifies the recorded defect annotation; it is not a claim that the current model successfully found it.</p>${list(item.modelFindings).length ? `<div class="case-model-findings">${list(item.modelFindings).map(finding => { const model = getVersion(finding.versionId); return `<span class="finding-chip"><strong>${escape(model?.name || finding.versionId || 'Model')}</strong>${escape(finding.predictedDefect === true || (!finding.abstained && ['DEFECT_SIGNAL', 'REVIEW_REQUIRED'].includes(finding.decision)) ? 'Defect flagged' : finding.abstained ? 'Abstained / review required' : 'MISSED DEFECT')}<span>Recorded score: ${finite(finding.score) ? Number(finding.score).toFixed(3) : '—'}</span></span>`; }).join('')}</div>` : ''}<div class="detail-section"><h3>Evidence binding</h3>${sourceBlock(evidence)}</div>${list(evidence.checks).length ? `<ul class="evidence-checks">${list(evidence.checks).map(check => `<li><span>${check.verified ? '✓' : '?'}</span>${escape(check.path || text(check))}</li>`).join('')}</ul>` : ''}<details style="margin-top:18px"><summary>Inspect the stored witness metadata</summary><pre>${escape(JSON.stringify({ witness, evidence }, null, 2))}</pre></details></article>`;
  }

  function renderResearch() {
    $('#research-error').hidden = !state.researchError;
    if (state.researchError) $('#research-error').innerHTML = `${escape(state.researchError)} <button id="retry-research" class="secondary-button">Reload research</button>`;
    const research = state.research || {}, papers = list(research.papers);
    $('#proposals').innerHTML = list(research.proposals).map((proposal, index) => `<article class="proposal"><div class="proposal-top"><span class="proposal-priority">EXPERIMENT ${String(index + 1).padStart(2, '0')}${proposal.priority ? ` / ${escape(text(proposal.priority).toUpperCase())}` : ''}</span><span class="outline-badge amber">NOT TRAINED</span></div><h3>${escape(proposal.name || proposal.title)}</h3><p>${escape(proposal.why || proposal.summary)}</p><details><summary>Method, risks & supporting papers</summary>${list(proposal.changes).length ? `<ul>${list(proposal.changes).map(change => `<li>${escape(text(change))}</li>`).join('')}</ul>` : ''}${list(proposal.risks).length ? `<p class="notice-line"><strong>Risks / limits</strong></p><ul>${list(proposal.risks).map(risk => `<li>${escape(text(risk))}</li>`).join('')}</ul>` : ''}<div class="paper-references">${list(proposal.paperIds).map(id => { const paper = papers.find(p => p.id === id); return paper ? `<a href="#paper-${escape(slug(id))}" data-paper-link="${escape(slug(id))}">${escape(paper.title)}</a>` : ''; }).join('')}</div></details></article>`).join('') || (state.researchError ? '' : '<div class="empty-state">No proposed experiments are recorded.</div>');
    $('#paper-grid').innerHTML = papers.map(paper => `<article class="paper" id="paper-${escape(slug(paper.id))}"><div class="paper-meta">${escape(paper.venue || 'PRIMARY PUBLICATION')} · ${escape(paper.year || '')}${paper.peerReviewed === false ? ' · PREPRINT' : ''}</div><h3>${escape(paper.title)}</h3><p class="authors">${escape(Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors || '')}</p><p>${escape(paper.relevance || paper.summary)}</p>${paper.limitation ? `<p class="limitation">${escape(paper.limitation)}</p>` : ''}${link(paper.url, 'Read the primary paper', 'paper-link')}</article>`).join('');
  }

  function navigate(view) {
    if (!viewNames[view]) view = 'overview';
    state.view = view;
    $$('.view').forEach(element => { element.hidden = element.id !== `view-${view}`; });
    $$('.nav-link').forEach(element => { const current = element.dataset.view === view; element.classList.toggle('active', current); if (current) element.setAttribute('aria-current', 'page'); else element.removeAttribute('aria-current'); });
    $('#breadcrumb-current').textContent = viewNames[view];
    if (!location.hash || location.hash.slice(1) !== view) history.replaceState(null, '', `#${view}`);
  }

  document.addEventListener('click', event => {
    if (event.target.closest('.skip-link')) { event.preventDefault(); $('#main').focus(); return; }
    const open = event.target.closest('[data-open-version]'); if (open) { openDetail(open.dataset.openVersion, open); return; }
    if (event.target.closest('[data-close-detail]') || event.target === $('#detail-overlay')) { closeDetail(); return; }
    const task = event.target.closest('[data-task]'); if (task) { state.task = task.dataset.task; state.assessment = 'default'; renderComparison(); return; }
    const metric = event.target.closest('[data-metric]'); if (metric) { state.metric = metric.dataset.metric; renderComparison(); return; }
    if (event.target.closest('[data-reset-filters]')) { $('#version-search').value = ''; $('#registry-task').value = 'all'; $('#registry-status').value = 'all'; renderRegistry(); return; }
    const paperLink = event.target.closest('[data-paper-link]'); if (paperLink) { event.preventDefault(); const paper = $(`#paper-${paperLink.dataset.paperLink}`); paper?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' }); paper?.setAttribute('tabindex', '-1'); paper?.focus({ preventScroll: true }); return; }
    if (event.target.closest('#retry-research')) { load(); return; }
  });
  $('#retry-button').addEventListener('click', load);
  $('#assessment-select').addEventListener('change', event => { state.assessment = event.target.value; renderComparison(); });
  $('#version-search').addEventListener('input', renderRegistry);
  $('#registry-task').addEventListener('change', renderRegistry);
  $('#registry-status').addEventListener('change', renderRegistry);
  $('#export-button').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify({ catalog: state.catalog, research: state.research }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'parity-benchmark-catalog.json'; document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000); toast('Repository-bound catalog downloaded.');
  });
  window.addEventListener('hashchange', () => { if (state.catalog) { navigate(location.hash.slice(1)); window.scrollTo(0, 0); } });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && state.detail) { closeDetail(); return; }
    if (event.key === 'Tab' && state.detail) {
      const nodes = $$('a[href],button:not([disabled]),input,select,summary,[tabindex="0"]', $('#version-detail')).filter(node => !node.hidden);
      const first = nodes[0], last = nodes.at(-1);
      if (event.shiftKey && (document.activeElement === first || document.activeElement === $('#version-detail'))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      return;
    }
    if (event.key === '/' && !state.detail && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) { event.preventDefault(); if (state.view !== 'versions') { location.hash = 'versions'; navigate('versions'); } $('#version-search').focus(); }
  });
  load();
})();
