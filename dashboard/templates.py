"""Server-rendered HTML templates for the SDLC dashboard using PatternFly 6."""

from __future__ import annotations

import json
from typing import Any

_PF_CSS_CDN = (
    "https://cdn.jsdelivr.net/npm/@patternfly/patternfly@6"
    "/patternfly.min.css"
)

_CSS = """
.sdlc-toast {
    position: fixed; top: 20px; right: 20px;
    max-width: 480px; z-index: 1000;
    opacity: 0; transition: opacity 0.3s;
}
.sdlc-toast.show { opacity: 1; }
.sdlc-section { margin-bottom: 24px; }
.pf-v6-c-table {
    border: 1px solid #475569;
}
.pf-v6-c-table th,
.pf-v6-c-table td {
    padding: 10px 16px;
}
.pf-v6-c-table thead th {
    border-bottom: 2px solid #475569;
}
.pf-v6-c-table tbody tr:not(:last-child) td {
    border-bottom: 1px solid #334155;
}
.pf-v6-c-page__sidebar { min-width: 300px; }
.sdlc-sidebar-links { list-style: none; padding: 0; margin: 0; }
.sdlc-sidebar-links li { margin-bottom: 4px; }
.sdlc-sidebar-links a {
    display: block; padding: 8px 16px;
    text-decoration: none; border-radius: 4px;
}
.sdlc-sidebar-links a:hover {
    background: rgba(255,255,255,.08);
}
.sdlc-sidebar-links .sub-label {
    display: block; padding: 8px 16px;
    font-size: 0.8rem; font-weight: 600;
    color: #94a3b8; cursor: default;
}
.sdlc-sidebar-links .sub a {
    padding-left: 32px; font-size: 0.82rem;
}
.sdlc-sidebar-section {
    border-bottom: 1px solid #334155;
    padding-bottom: 8px; margin-bottom: 8px;
}
.sdlc-diagram { margin: 16px 0; overflow-x: auto; }
.sdlc-diagram svg { display: block; margin: 0 auto; }
.sdlc-phase rect {
    fill: #1e293b; stroke: #475569;
    stroke-width: 1.5; rx: 6; ry: 6;
    transition: all 0.3s;
}
.sdlc-phase-done rect {
    fill: #14532d; stroke: #22c55e; stroke-width: 1.5;
}
.sdlc-phase-active rect {
    fill: #1e3a5f; stroke: #3b82f6; stroke-width: 2.5;
}
.sdlc-phase .phase-letter {
    fill: #94a3b8; font-size: 10px; font-weight: 700;
}
.sdlc-phase .phase-label {
    fill: #f1f5f9; font-size: 11px;
}
.sdlc-phase-done .phase-letter { fill: #86efac; }
.sdlc-phase-active .phase-letter { fill: #93c5fd; }
.sdlc-phase-active .phase-label { fill: #ffffff; }
.sdlc-arrow { stroke: #475569; fill: none; stroke-width: 1.5; }
.sdlc-arrow-head {
    fill: #475569; stroke: none;
}
.sdlc-wf-row { cursor: pointer; }
.sdlc-wf-row:hover td { background: rgba(255,255,255,.04); }
.sdlc-wf-selected td {
    background: rgba(59,130,246,.1) !important;
}
.sdlc-detail-row td {
    padding: 0 16px 12px 16px;
    background: rgba(59,130,246,.04);
}
.sdlc-pr-list {
    list-style: none; padding: 4px 0; margin: 0;
}
.sdlc-pr-list li {
    padding: 4px 0; font-size: 0.85rem;
    display: flex; align-items: center; gap: 8px;
}
.sdlc-pr-type {
    display: inline-block; min-width: 90px;
}
.sdlc-diagram-hint {
    text-align: center; color: #94a3b8;
    font-size: 0.85rem; padding: 8px 0;
}
"""

_JS = """
const WORKFLOW_TYPES = __WORKFLOW_TYPES__;
const PHASES = ['A','B','C','D','E','F','G','H','I','J'];

let currentType = '';
let selectedRunId = null;

function selectWorkflow(type) {
    currentType = type;
    const info = WORKFLOW_TYPES[type];
    document.getElementById('wf-desc').textContent = info.description;
    const container = document.getElementById('wf-fields');
    container.innerHTML = '';
    info.fields.forEach(f => {
        if (f.type === 'checkbox') {
            const div = document.createElement('div');
            div.className = 'pf-v6-c-check';
            div.innerHTML =
                `<input class="pf-v6-c-check__input" type="checkbox"
                    id="field-${f.name}" name="${f.name}">` +
                `<label class="pf-v6-c-check__label"
                    for="field-${f.name}">${f.label}</label>`;
            const group = document.createElement('div');
            group.className = 'pf-v6-c-form__group';
            group.appendChild(div);
            container.appendChild(group);
        } else {
            const group = document.createElement('div');
            group.className = 'pf-v6-c-form__group';
            const req = f.required ? ' required' : '';
            const reqMark = f.required
                ? `<span class="pf-v6-c-form__label-required"
                    aria-hidden="true">&#42;</span>` : '';
            group.innerHTML =
                `<label class="pf-v6-c-form__label"
                    for="field-${f.name}">` +
                `<span class="pf-v6-c-form__label-text">${f.label}` +
                `</span>` + reqMark + `</label>`;
            if (f.multiline) {
                group.innerHTML +=
                    `<span class="pf-v6-c-form-control">` +
                    `<textarea id="field-${f.name}" name="${f.name}"
                        placeholder="${f.placeholder || ''}"
                        rows="3"${req}></textarea></span>`;
            } else {
                group.innerHTML +=
                    `<span class="pf-v6-c-form-control">` +
                    `<input type="text" id="field-${f.name}"
                        name="${f.name}"
                        placeholder="${f.placeholder || ''}"
                        value="${f.default || ''}"${req}></span>`;
            }
            container.appendChild(group);
        }
    });
    document.getElementById('wf-fields-wrap').style.display = 'block';
}

function showToast(msg, type) {
    const el = document.getElementById('toast');
    const pfType = type === 'success' ? 'pf-m-success' : 'pf-m-danger';
    el.className =
        'sdlc-toast pf-v6-c-alert pf-m-inline ' + pfType + ' show';
    el.innerHTML =
        `<div class="pf-v6-c-alert__title">${msg}</div>`;
    setTimeout(() => { el.className = 'sdlc-toast'; }, 6000);
}

async function triggerWorkflow() {
    if (!currentType) return;
    const info = WORKFLOW_TYPES[currentType];
    const inputs = {};
    for (const f of info.fields) {
        const el = document.getElementById('field-' + f.name);
        if (!el) continue;
        if (f.type === 'checkbox') {
            inputs[f.name] = el.checked;
        } else {
            const val = el.value.trim();
            if (f.required && !val) {
                showToast(`Field "${f.label}" is required`, 'error');
                el.focus();
                return;
            }
            if (val) inputs[f.name] = val;
        }
    }

    const btn = document.getElementById('btn-trigger');
    btn.disabled = true;
    btn.textContent = 'Starting...';

    try {
        const resp = await fetch('/api/workflows/trigger', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({task_type: currentType, inputs}),
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast(
                `Workflow <b>${data.workflow_id}</b> started. ` +
                `<a href="${data.temporal_ui_url}"` +
                ` target="_blank">Open in Temporal UI</a>`,
                'success'
            );
            refreshWorkflows();
        } else {
            showToast('Error: ' +
                (data.detail || JSON.stringify(data)), 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Trigger Workflow';
    }
}

// ── Workflows ────────────────────────────────────────────────────

function timeAgo(iso) {
    if (!iso) return '';
    const ms = Date.now() - new Date(iso).getTime();
    const sec = Math.floor(ms / 1000);
    if (sec < 60) return sec + 's ago';
    const min = Math.floor(sec / 60);
    if (min < 60) return min + 'm ago';
    const hr = Math.floor(min / 60);
    if (hr < 24) return hr + 'h ago';
    return Math.floor(hr / 24) + 'd ago';
}

function fmtTokens(w) {
    return w.total_tokens
        ? w.total_tokens.toLocaleString() : '\\u2014';
}

function statusColor(status) {
    if (status === 'RUNNING') return 'pf-m-blue';
    if (status === 'COMPLETED') return 'pf-m-green';
    if (status === 'FAILED' || status === 'TIMED_OUT')
        return 'pf-m-red';
    return '';
}

function fmtStatusMsg(w) {
    if (!w.status_message) return '';
    let ago = '';
    if (w.status_timestamp) ago = ' · ' + timeAgo(w.status_timestamp);
    return `<div style="font-size:0.78rem;color:#94a3b8;` +
        `margin-top:2px;line-height:1.3">` +
        `${w.status_message}${ago}</div>`;
}

function prStatusColor(status) {
    if (status === 'Generating' || status === 'Testing')
        return 'pf-m-blue';
    if (status === 'Monitoring') return 'pf-m-cyan';
    if (status === 'Complete') return 'pf-m-green';
    if (status === 'Failed') return 'pf-m-red';
    return '';
}

async function refreshWorkflows() {
    try {
        const resp = await fetch('/api/workflows');
        const data = await resp.json();
        renderWorkflowsTable(data.workflows);
        syncDiagram(data.workflows);
    } catch (err) {
        console.error('Workflow list failed:', err);
    }
}

function syncDiagram(workflows) {
    if (!workflows || workflows.length === 0) {
        highlightPhase('');
        return;
    }
    // If user clicked a row, track that workflow's phase
    if (selectedRunId) {
        const sel = workflows.find(w => w.run_id === selectedRunId);
        if (sel && sel.current_phase) {
            highlightPhase(sel.current_phase);
            return;
        }
    }
    // Otherwise auto-select the first running full_sdlc workflow
    const running = workflows.find(
        w => w.task_type === 'full_sdlc' && w.current_phase
    );
    if (running) {
        selectedRunId = running.run_id;
        highlightPhase(running.current_phase);
        const hint = document.getElementById('diagram-hint');
        if (hint) hint.style.display = 'none';
    }
}

let expandedRunId = null;
let allWorkflows = [];
let wfPage = 0;
const WF_PAGE_SIZE = 5;

function renderWorkflowsTable(workflows) {
    allWorkflows = workflows;
    const tbody = document.getElementById('workflows-body');
    if (!workflows || workflows.length === 0) {
        tbody.innerHTML =
            '<tr><td role="gridcell" colspan="7">' +
            'No workflows found</td></tr>';
        renderPagination();
        return;
    }
    const totalPages = Math.ceil(workflows.length / WF_PAGE_SIZE);
    if (wfPage >= totalPages) wfPage = totalPages - 1;
    const start = wfPage * WF_PAGE_SIZE;
    const page = workflows.slice(start, start + WF_PAGE_SIZE);
    let rows = '';
    for (const w of page) {
        const color = statusColor(w.status);
        const phase = w.current_phase
            ? w.current_phase + ': ' + w.current_phase_label
            : '\\u2014';
        const statusMsg = fmtStatusMsg(w);
        const sel = w.run_id === selectedRunId
            ? ' sdlc-wf-selected' : '';
        rows +=
            `<tr role="row" class="sdlc-wf-row${sel}"` +
            ` onclick="toggleDetail('${w.run_id}',` +
            `'${w.current_phase || ''}',` +
            `'${w.task_type}')">` +
            `<td role="gridcell"><span` +
            ` class="pf-v6-c-label pf-m-compact ${color}">` +
            `<span class="pf-v6-c-label__content">${w.status}` +
            `</span></span></td>` +
            `<td role="gridcell">${w.task_type_label}</td>` +
            `<td role="gridcell"><code>${w.run_id}</code></td>` +
            `<td role="gridcell">${phase}${statusMsg}</td>` +
            `<td role="gridcell">${fmtTokens(w)}</td>` +
            `<td role="gridcell">${timeAgo(w.start_time)}</td>` +
            `<td role="gridcell">` +
            `<a class="pf-v6-c-button pf-m-link pf-m-small"` +
            ` href="${w.temporal_ui_url}" target="_blank"` +
            ` onclick="event.stopPropagation()">View` +
            `</a></td></tr>`;
        if (w.run_id === expandedRunId) {
            rows +=
                `<tr class="sdlc-detail-row">` +
                `<td colspan="7" id="detail-${w.run_id}">` +
                `Loading PRs...</td></tr>`;
        }
    }
    tbody.innerHTML = rows;
    renderPagination();
    if (expandedRunId) fetchPRs(expandedRunId);
}

function renderPagination() {
    const container = document.getElementById('wf-pagination');
    if (!allWorkflows || allWorkflows.length <= WF_PAGE_SIZE) {
        container.innerHTML = '';
        return;
    }
    const totalPages = Math.ceil(
        allWorkflows.length / WF_PAGE_SIZE);
    const prevDis = wfPage === 0 ? ' disabled' : '';
    const nextDis = wfPage >= totalPages - 1 ? ' disabled' : '';
    container.innerHTML =
        `<button class="pf-v6-c-button pf-m-secondary` +
        ` pf-m-small"${prevDis}` +
        ` onclick="wfPageNav(-1)">Previous</button>` +
        `<span style="font-size:0.85rem;color:#94a3b8">` +
        `${wfPage + 1} / ${totalPages}</span>` +
        `<button class="pf-v6-c-button pf-m-secondary` +
        ` pf-m-small"${nextDis}` +
        ` onclick="wfPageNav(1)">Next</button>`;
}

function wfPageNav(delta) {
    wfPage += delta;
    renderWorkflowsTable(allWorkflows);
}

async function toggleDetail(runId, phase, taskType) {
    if (taskType === 'full_sdlc') {
        selectedRunId = runId;
        highlightPhase(phase);
        const hint = document.getElementById('diagram-hint');
        if (hint) hint.style.display = 'none';
    }
    if (expandedRunId === runId) {
        expandedRunId = null;
    } else {
        expandedRunId = runId;
    }
    refreshWorkflows();
}

async function fetchPRs(runId) {
    const cell = document.getElementById('detail-' + runId);
    if (!cell) return;
    try {
        const resp = await fetch('/api/workflows/' + runId + '/prs');
        const data = await resp.json();
        if (!data.prs || data.prs.length === 0) {
            cell.innerHTML = '<em>No PRs found yet</em>';
            return;
        }
        let items = '';
        for (const pr of data.prs) {
            const lbl = pr.type === 'enhancement'
                ? '<span class="pf-v6-c-label pf-m-compact' +
                  ' pf-m-blue"><span' +
                  ' class="pf-v6-c-label__content">' +
                  'Enhancement</span></span>'
                : '<span class="pf-v6-c-label pf-m-compact">' +
                  '<span class="pf-v6-c-label__content">' +
                  'Staging</span></span>';
            const title = pr.title
                ? ' &mdash; ' + pr.title : '';
            let statusLbl = '';
            if (pr.status) {
                const sc = prStatusColor(pr.status);
                statusLbl =
                    `<span class="pf-v6-c-label pf-m-compact` +
                    ` ${sc}"><span` +
                    ` class="pf-v6-c-label__content">` +
                    `${pr.status}</span></span>`;
            }
            items +=
                `<li>${lbl} ${statusLbl}` +
                `<span class="sdlc-pr-type">${pr.repo}</span>` +
                `<a href="${pr.url}" target="_blank">` +
                `#${pr.number}${title}</a></li>`;
        }
        cell.innerHTML =
            '<ul class="sdlc-pr-list">' + items + '</ul>';
    } catch (err) {
        cell.innerHTML = '<em>Failed to load PRs</em>';
    }
}

function highlightPhase(activePhase) {
    const idx = PHASES.indexOf(activePhase);
    PHASES.forEach((p, i) => {
        const el = document.getElementById('phase-' + p);
        if (!el) return;
        el.classList.remove('sdlc-phase-done', 'sdlc-phase-active');
        if (idx < 0) return;
        if (i < idx) el.classList.add('sdlc-phase-done');
        else if (i === idx) el.classList.add('sdlc-phase-active');
    });
}

// ── Init ─────────────────────────────────────────────────────────

refreshWorkflows();
setInterval(refreshWorkflows, 10000);
"""

_SVG_DIAGRAM = """\
<svg viewBox="0 0 820 180" xmlns="http://www.w3.org/2000/svg"
    width="820" height="180">
  <defs>
    <marker id="ah" markerWidth="8" markerHeight="6"
        refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" class="sdlc-arrow-head"/>
    </marker>
  </defs>

  <!-- Row 1: A → B → C → D → E -->
  <g id="phase-A" class="sdlc-phase">
    <rect x="10" y="20" width="130" height="50"/>
    <text x="75" y="40" text-anchor="middle" class="phase-letter">A</text>
    <text x="75" y="56" text-anchor="middle" class="phase-label">Ensure Epic</text>
  </g>
  <line x1="140" y1="45" x2="160" y2="45" class="sdlc-arrow" marker-end="url(#ah)"/>

  <g id="phase-B" class="sdlc-phase">
    <rect x="170" y="20" width="130" height="50"/>
    <text x="235" y="40" text-anchor="middle" class="phase-letter">B</text>
    <text x="235" y="56" text-anchor="middle" class="phase-label">Enhancement</text>
  </g>
  <line x1="300" y1="45" x2="320" y2="45" class="sdlc-arrow" marker-end="url(#ah)"/>

  <g id="phase-C" class="sdlc-phase">
    <rect x="330" y="20" width="130" height="50"/>
    <text x="395" y="40" text-anchor="middle" class="phase-letter">C</text>
    <text x="395" y="56" text-anchor="middle" class="phase-label">Approval Gate</text>
  </g>
  <line x1="460" y1="45" x2="480" y2="45" class="sdlc-arrow" marker-end="url(#ah)"/>

  <g id="phase-D" class="sdlc-phase">
    <rect x="490" y="20" width="130" height="50"/>
    <text x="555" y="40" text-anchor="middle" class="phase-letter">D</text>
    <text x="555" y="56" text-anchor="middle" class="phase-label">Mirror &amp; Fork</text>
  </g>
  <line x1="620" y1="45" x2="640" y2="45" class="sdlc-arrow" marker-end="url(#ah)"/>

  <g id="phase-E" class="sdlc-phase">
    <rect x="650" y="20" width="130" height="50"/>
    <text x="715" y="40" text-anchor="middle" class="phase-letter">E</text>
    <text x="715" y="56" text-anchor="middle" class="phase-label">Feature Analysis</text>
  </g>

  <!-- Connector E down to F -->
  <line x1="715" y1="70" x2="715" y2="100" class="sdlc-arrow" marker-end="url(#ah)"/>

  <!-- Row 2: F → G → H → I → J (right to left visually, but drawn left to right) -->
  <g id="phase-F" class="sdlc-phase">
    <rect x="650" y="110" width="130" height="50"/>
    <text x="715" y="130" text-anchor="middle" class="phase-letter">F</text>
    <text x="715" y="146" text-anchor="middle" class="phase-label">Story Refinement</text>
  </g>
  <line x1="650" y1="135" x2="630" y2="135" class="sdlc-arrow" marker-end="url(#ah)"/>

  <g id="phase-G" class="sdlc-phase">
    <rect x="490" y="110" width="130" height="50"/>
    <text x="555" y="130" text-anchor="middle" class="phase-letter">G</text>
    <text x="555" y="146" text-anchor="middle" class="phase-label">Create Stories</text>
  </g>
  <line x1="490" y1="135" x2="470" y2="135" class="sdlc-arrow" marker-end="url(#ah)"/>

  <g id="phase-H" class="sdlc-phase">
    <rect x="330" y="110" width="130" height="50"/>
    <text x="395" y="130" text-anchor="middle" class="phase-letter">H</text>
    <text x="395" y="146" text-anchor="middle" class="phase-label">Setup Staging</text>
  </g>
  <line x1="330" y1="135" x2="310" y2="135" class="sdlc-arrow" marker-end="url(#ah)"/>

  <g id="phase-I" class="sdlc-phase">
    <rect x="170" y="110" width="130" height="50"/>
    <text x="235" y="130" text-anchor="middle" class="phase-letter">I</text>
    <text x="235" y="146" text-anchor="middle" class="phase-label">Implement</text>
  </g>
  <line x1="170" y1="135" x2="150" y2="135" class="sdlc-arrow" marker-end="url(#ah)"/>

  <g id="phase-J" class="sdlc-phase">
    <rect x="10" y="110" width="130" height="50"/>
    <text x="75" y="130" text-anchor="middle" class="phase-letter">J</text>
    <text x="75" y="146" text-anchor="middle" class="phase-label">Monitor PRs</text>
  </g>
</svg>"""


def render_dashboard(
    workflow_types: dict[str, dict[str, Any]],
    external_urls: dict[str, str],
) -> str:
    wf_options = ""
    for key, info in workflow_types.items():
        wf_options += (
            f'<option value="{key}">{info["label"]}</option>\n'
        )

    sidebar_links_html = ""
    link_items = [
        ("Temporal UI",
         external_urls.get("Temporal UI", "http://localhost:8233")),
        ("RustFS Console",
         external_urls.get("RustFS (S3)", "http://localhost:9001")),
        ("Gitea",
         external_urls.get("Gitea", "http://localhost:3000")),
        ("Jira Simulator",
         external_urls.get("Jira Simulator", "http://localhost:8080")),
    ]
    for label, url in link_items:
        sidebar_links_html += (
            f'<li><a href="{url}" target="_blank">'
            f'{label}</a></li>\n'
        )

    js = _JS.replace("__WORKFLOW_TYPES__", json.dumps(workflow_types))

    return f"""<!DOCTYPE html>
<html lang="en" class="pf-v6-theme-dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
        content="width=device-width, initial-scale=1.0">
    <title>SDLC Dashboard</title>
    <link rel="stylesheet" href="{_PF_CSS_CDN}">
    <style>{_CSS}</style>
</head>
<body>
<div class="pf-v6-c-page">

    <header class="pf-v6-c-masthead">
        <div class="pf-v6-c-masthead__main">
            <span class="pf-v6-c-masthead__brand">
                SDLC Workflow Dashboard
            </span>
        </div>
    </header>

    <div class="pf-v6-c-page__sidebar pf-m-expanded">
        <div class="pf-v6-c-page__sidebar-body">

            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Navigation
                </h3>
                <ul class="sdlc-sidebar-links">
                    <li><a href="/">Dashboard</a></li>
                    <li><a href="/settings">
                        Settings</a></li>
                    <li><a href="/status">
                        Service Status</a></li>
                    <li><span class="sub-label">
                        Developer</span></li>
                    <li class="sub"><a href="/dev">
                        Editor</a></li>
                    <li class="sub"><a href="/dev/tokens">
                        Token Usage</a></li>
                </ul>
            </div>

            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Quick Links
                </h3>
                <ul class="sdlc-sidebar-links">
                    {sidebar_links_html}
                </ul>
            </div>

        </div>
    </div>

    <main class="pf-v6-c-page__main" tabindex="-1">
    <section class="pf-v6-c-page__main-section">

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">Workflows</h2>
            <table class="pf-v6-c-table pf-m-compact"
                role="grid" aria-label="Running workflows">
                <thead>
                    <tr role="row">
                        <th role="columnheader">Status</th>
                        <th role="columnheader">Type</th>
                        <th role="columnheader">Run ID</th>
                        <th role="columnheader">Phase</th>
                        <th role="columnheader">Tokens</th>
                        <th role="columnheader">Started</th>
                        <th role="columnheader"></th>
                    </tr>
                </thead>
                <tbody id="workflows-body" role="rowgroup">
                    <tr role="row">
                        <td role="gridcell" colspan="7">
                            Loading...
                        </td>
                    </tr>
                </tbody>
            </table>
            <div id="wf-pagination"
                style="display:flex; align-items:center;
                    gap:8px; padding:8px 0">
            </div>
        </div>

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">
                SDLC Lifecycle
            </h2>
            <p id="diagram-hint" class="sdlc-diagram-hint">
                Click a Full SDLC workflow above to highlight
                its current phase
            </p>
            <div class="sdlc-diagram">
                {_SVG_DIAGRAM}
            </div>
        </div>

        <div class="sdlc-section">
            <div class="pf-v6-c-card">
                <div class="pf-v6-c-card__header">
                    <div class="pf-v6-c-card__title">
                        <h2 class="pf-v6-c-title pf-m-lg">
                            Trigger Workflow
                        </h2>
                    </div>
                </div>
                <div class="pf-v6-c-card__body">
                    <form class="pf-v6-c-form">
                        <div class="pf-v6-c-form__group">
                            <label class="pf-v6-c-form__label"
                                for="wf-select">
                                <span
                                  class="pf-v6-c-form__label-text">
                                    Workflow Type
                                </span>
                            </label>
                            <span class="pf-v6-c-form-control">
                                <select id="wf-select"
                                  onchange="selectWorkflow(
                                    this.value)">
                                    <option value="">
                                        Select a workflow
                                    </option>
                                    {wf_options}
                                </select>
                            </span>
                        </div>
                        <div id="wf-fields-wrap"
                            style="display:none">
                            <p id="wf-desc"
                              class="pf-v6-c-form__helper-text">
                            </p>
                            <div id="wf-fields"></div>
                            <div class="pf-v6-c-form__group">
                                <button id="btn-trigger"
                                  type="button"
                                  class="pf-v6-c-button pf-m-primary"
                                  onclick="triggerWorkflow()">
                                    Trigger Workflow
                                </button>
                            </div>
                        </div>
                    </form>
                </div>
            </div>
        </div>

    </section>
    </main>

</div>

<div id="toast" class="sdlc-toast"></div>
<script>{js}</script>
</body>
</html>"""


_STATUS_JS = """
async function refreshHealth() {
    try {
        const resp = await fetch('/api/health');
        const data = await resp.json();
        renderHealthTable('infra-body', data.infra);
        renderHealthTable('worker-body', data.workers);
    } catch (err) {
        console.error('Health check failed:', err);
    }
}

function renderHealthTable(tbodyId, items) {
    const tbody = document.getElementById(tbodyId);
    let rows = '';
    for (const s of items) {
        const color = s.healthy ? 'pf-m-green' : 'pf-m-red';
        const text = s.healthy ? 'Healthy' : 'Down';
        const link = s.url
            ? `<a class="pf-v6-c-button pf-m-link pf-m-small"` +
              ` href="${s.url}" target="_blank">Open</a>` : '';
        rows +=
            `<tr role="row">` +
            `<td role="gridcell"><span` +
            ` class="pf-v6-c-label pf-m-compact ${color}">` +
            `<span class="pf-v6-c-label__content">${text}` +
            `</span></span></td>` +
            `<td role="gridcell">${s.name}</td>` +
            `<td role="gridcell">${s.detail}</td>` +
            `<td role="gridcell">${link}</td></tr>`;
    }
    tbody.innerHTML = rows;
}

refreshHealth();
setInterval(refreshHealth, 10000);
"""


def render_status_page(external_urls: dict[str, str]) -> str:
    sidebar_links_html = ""
    link_items = [
        ("Temporal UI",
         external_urls.get("Temporal UI", "http://localhost:8233")),
        ("RustFS Console",
         external_urls.get("RustFS (S3)", "http://localhost:9001")),
        ("Gitea",
         external_urls.get("Gitea", "http://localhost:3000")),
        ("Jira Simulator",
         external_urls.get("Jira Simulator", "http://localhost:8080")),
    ]
    for label, url in link_items:
        sidebar_links_html += (
            f'<li><a href="{url}" target="_blank">'
            f'{label}</a></li>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en" class="pf-v6-theme-dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
        content="width=device-width, initial-scale=1.0">
    <title>Service Status — SDLC Dashboard</title>
    <link rel="stylesheet" href="{_PF_CSS_CDN}">
    <style>{_CSS}</style>
</head>
<body>
<div class="pf-v6-c-page">

    <header class="pf-v6-c-masthead">
        <div class="pf-v6-c-masthead__main">
            <span class="pf-v6-c-masthead__brand">
                SDLC Workflow Dashboard
            </span>
        </div>
    </header>

    <div class="pf-v6-c-page__sidebar pf-m-expanded">
        <div class="pf-v6-c-page__sidebar-body">

            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Navigation
                </h3>
                <ul class="sdlc-sidebar-links">
                    <li><a href="/">Dashboard</a></li>
                    <li><a href="/settings">
                        Settings</a></li>
                    <li><a href="/status">
                        Service Status</a></li>
                    <li><span class="sub-label">
                        Developer</span></li>
                    <li class="sub"><a href="/dev">
                        Editor</a></li>
                    <li class="sub"><a href="/dev/tokens">
                        Token Usage</a></li>
                </ul>
            </div>

            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Quick Links
                </h3>
                <ul class="sdlc-sidebar-links">
                    {sidebar_links_html}
                </ul>
            </div>

        </div>
    </div>

    <main class="pf-v6-c-page__main" tabindex="-1">
    <section class="pf-v6-c-page__main-section">

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">
                Infrastructure
            </h2>
            <table class="pf-v6-c-table pf-m-compact"
                role="grid"
                aria-label="Infrastructure health">
                <thead>
                    <tr role="row">
                        <th role="columnheader">Status</th>
                        <th role="columnheader">Service</th>
                        <th role="columnheader">Detail</th>
                        <th role="columnheader"></th>
                    </tr>
                </thead>
                <tbody id="infra-body" role="rowgroup">
                    <tr role="row">
                        <td role="gridcell" colspan="4">
                            Loading...
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">
                Agent Workers
            </h2>
            <table class="pf-v6-c-table pf-m-compact"
                role="grid"
                aria-label="Agent worker health">
                <thead>
                    <tr role="row">
                        <th role="columnheader">Status</th>
                        <th role="columnheader">Worker</th>
                        <th role="columnheader">Detail</th>
                        <th role="columnheader"></th>
                    </tr>
                </thead>
                <tbody id="worker-body" role="rowgroup">
                    <tr role="row">
                        <td role="gridcell" colspan="4">
                            Loading...
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>

    </section>
    </main>

</div>

<script>{_STATUS_JS}</script>
</body>
</html>"""


_DEV_CSS = """
.sdlc-rerun-bar {
    display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px;
}
.sdlc-editor {
    display: flex; border: 1px solid #334155;
    border-radius: 6px; overflow: hidden;
    height: 600px;
}
.sdlc-editor-sidebar {
    width: 240px; min-width: 200px;
    border-right: 1px solid #334155;
    overflow-y: auto; background: #1e293b;
}
.sdlc-editor-sidebar .folder {
    padding: 6px 12px; font-size: 0.75rem;
    color: #94a3b8; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.sdlc-editor-sidebar .file {
    display: block; padding: 6px 12px 6px 24px;
    font-size: 0.85rem; cursor: pointer;
    text-decoration: none; color: #f1f5f9;
    border-left: 3px solid transparent;
}
.sdlc-editor-sidebar .file:hover {
    background: rgba(255,255,255,.06);
}
.sdlc-editor-sidebar .file.active {
    background: rgba(59,130,246,.15);
    border-left-color: #3b82f6;
    color: #ffffff;
}
.sdlc-editor-main {
    flex: 1; display: flex; flex-direction: column;
    min-width: 0;
}
.sdlc-editor-tab {
    display: flex; align-items: center;
    justify-content: space-between;
    padding: 6px 14px; background: #1e293b;
    border-bottom: 1px solid #334155;
    font-size: 0.85rem; color: #94a3b8;
}
.sdlc-editor-tab .tab-name {
    font-weight: 600; color: #f1f5f9;
}
.sdlc-editor-content {
    flex: 1; position: relative; overflow: hidden;
}
.sdlc-editor-status {
    display: flex; align-items: center;
    justify-content: space-between;
    padding: 4px 14px; background: #1e293b;
    border-top: 1px solid #334155;
    font-size: 0.8rem; color: #94a3b8;
}
"""

_DEV_JS = """
let devRunId = null;

async function loadRuns() {
    try {
        const resp = await fetch('/api/workflows');
        const data = await resp.json();
        const sel = document.getElementById('dev-run-select');
        const seen = new Set();
        for (const w of data.workflows) {
            if (seen.has(w.run_id)) continue;
            seen.add(w.run_id);
            const opt = document.createElement('option');
            opt.value = w.run_id;
            opt.textContent =
                w.run_id + ' (' + w.task_type_label + ')';
            sel.appendChild(opt);
        }
    } catch (err) {
        console.error('Failed to load runs:', err);
    }
}

async function selectRun(runId) {
    if (!runId) {
        devRunId = null;
        document.getElementById('dev-rerun').innerHTML = '';
        renderEditorSidebar();
        return;
    }
    devRunId = runId;
    try {
        const resp = await fetch(
            '/api/dev/runs/' + runId + '/artifacts');
        const data = await resp.json();
        artifactFiles = (data.artifacts || []).map(a => ({
            path: a.key,
            content: JSON.stringify(a.data, null, 2),
            type: 'artifact',
        }));
        renderRerunButtons(data.artifacts || []);
        renderEditorSidebar();
    } catch (err) {
        artifactFiles = [];
        renderEditorSidebar();
    }
}

function escHtml(s) {
    return s.replace(/&/g, '&amp;')
        .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Unified editor ──────────────────────────────────────────

let promptFiles = [];
let artifactFiles = [];
let activeFile = null;
let editorDirty = false;
let suppressDirty = false;

async function loadPrompts() {
    try {
        const resp = await fetch('/api/dev/prompts');
        const data = await resp.json();
        promptFiles = (data.templates || []).map(t => ({
            path: t.path,
            content: t.content,
            type: 'prompt',
        }));
        renderEditorSidebar();
    } catch (err) {
        promptFiles = [];
        renderEditorSidebar();
    }
}

function renderEditorSidebar() {
    const container = document.getElementById(
        'editor-file-list');
    if (!container) return;
    let html = '';

    if (artifactFiles.length > 0) {
        html += `<div class="folder">artifacts (${devRunId})</div>`;
        for (const f of artifactFiles) {
            const active = activeFile === f ? ' active' : '';
            html +=
                `<div class="file${active}"` +
                ` onclick="openFileByKey('artifact',` +
                `'${escHtml(f.path)}')">${f.path}</div>`;
        }
    }

    let lastFolder = '';
    if (promptFiles.length > 0) {
        for (const f of promptFiles) {
            const parts = f.path.split('/');
            const folder = parts.length > 1
                ? parts.slice(0, -1).join('/') : 'prompts';
            const file = parts[parts.length - 1];
            if (folder !== lastFolder) {
                html += `<div class="folder">${folder}</div>`;
                lastFolder = folder;
            }
            const active = activeFile === f ? ' active' : '';
            html +=
                `<div class="file${active}"` +
                ` onclick="openFileByKey('prompt',` +
                `'${escHtml(f.path)}')">${file}</div>`;
        }
    }

    container.innerHTML = html || '<div style="padding:12px;' +
        'color:#94a3b8">No files</div>';
}

function openFileByKey(type, path) {
    const list = type === 'artifact'
        ? artifactFiles : promptFiles;
    const f = list.find(x => x.path === path);
    if (f) openFile(f);
}

let monacoEditor = null;

function initMonaco() {
    require.config({
        paths: {
            vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2' +
                '/min/vs'
        }
    });
    require(['vs/editor/editor.main'], function () {
        monaco.editor.defineTheme('sdlc-dark', {
            base: 'vs-dark',
            inherit: true,
            rules: [],
            colors: {
                'editor.background': '#0f172a',
            },
        });
        monacoEditor = monaco.editor.create(
            document.getElementById('editor-container'), {
                value: '',
                language: 'markdown',
                theme: 'sdlc-dark',
                fontSize: 13,
                minimap: { enabled: true },
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 4,
                insertSpaces: true,
            }
        );
        monacoEditor.onDidChangeModelContent(() => {
            if (suppressDirty) return;
            editorDirty = true;
            const s = document.getElementById(
                'editor-status-text');
            if (s) s.textContent = 'Modified';
        });
        monacoEditor.addAction({
            id: 'save-file',
            label: 'Save',
            keybindings: [
                monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
            ],
            run: function () { saveCurrentFile(); },
        });
        if (promptFiles.length > 0) openFile(promptFiles[0]);
    });
}

function monacoLang(path) {
    if (path.endsWith('.json')) return 'json';
    if (path.endsWith('.md')) return 'markdown';
    if (path.endsWith('.yaml') || path.endsWith('.yml'))
        return 'yaml';
    return 'plaintext';
}

function openFile(f) {
    if (editorDirty && activeFile) {
        if (!confirm('Discard unsaved changes?')) return;
    }
    activeFile = f;
    editorDirty = false;
    const tabName = document.getElementById('editor-tab-name');
    const status = document.getElementById('editor-status-text');
    if (tabName) tabName.textContent =
        (f.type === 'artifact' ? 'artifact: ' : '') + f.path;
    if (status) status.textContent = 'Ready';
    if (monacoEditor) {
        suppressDirty = true;
        const lang = monacoLang(f.path);
        const model = monacoEditor.getModel();
        monaco.editor.setModelLanguage(model, lang);
        monacoEditor.setValue(f.content);
        suppressDirty = false;
    }
    renderEditorSidebar();
}

async function saveCurrentFile() {
    if (!activeFile || !monacoEditor) return;
    const value = monacoEditor.getValue();
    const status = document.getElementById('editor-status-text');
    if (status) status.textContent = 'Saving...';

    if (activeFile.type === 'artifact') {
        let parsed;
        try {
            parsed = JSON.parse(value);
        } catch (err) {
            showToast('Invalid JSON: ' + err.message, 'error');
            if (status) status.textContent = 'Error';
            return;
        }
        try {
            const resp = await fetch(
                '/api/dev/runs/' + devRunId +
                '/artifacts/' + activeFile.path,
                {method: 'PUT',
                 headers: {'Content-Type': 'application/json'},
                 body: JSON.stringify(parsed)});
            const data = await resp.json();
            if (resp.ok) {
                activeFile.content = value;
                editorDirty = false;
                if (status) status.textContent = 'Saved';
                showToast('Saved ' + activeFile.path,
                    'success');
            } else {
                if (status) status.textContent = 'Error';
                showToast('Error: ' +
                    (data.detail || 'save failed'), 'error');
            }
        } catch (err) {
            if (status) status.textContent = 'Error';
            showToast('Network error: ' + err.message,
                'error');
        }
    } else {
        try {
            const resp = await fetch(
                '/api/dev/prompts/' + activeFile.path,
                {method: 'PUT',
                 headers: {'Content-Type': 'text/plain'},
                 body: value});
            const data = await resp.json();
            if (resp.ok) {
                activeFile.content = value;
                editorDirty = false;
                if (status) status.textContent = 'Saved';
                showToast('Saved ' + activeFile.path,
                    'success');
            } else {
                if (status) status.textContent = 'Error';
                showToast('Error: ' +
                    (data.detail || 'save failed'), 'error');
            }
        } catch (err) {
            if (status) status.textContent = 'Error';
            showToast('Network error: ' + err.message,
                'error');
        }
    }
}

const RERUN_STEPS = {
    'generate_code': {
        label: 'Code Generation',
        needs: ['staging-plan.json',
            'openshift-feature-plan.json'],
    },
    'analyze_feature': {
        label: 'Feature Analysis',
        needs: ['enhancement-doc.json'],
    },
};

function renderRerunButtons(artifacts) {
    const container = document.getElementById('dev-rerun');
    const keys = new Set(artifacts.map(a => a.key));
    let html = '';
    for (const [step, info] of Object.entries(RERUN_STEPS)) {
        const hasDeps = info.needs.every(k => keys.has(k));
        const disabled = hasDeps ? '' : ' disabled';
        const title = hasDeps ? ''
            : ` title="Missing: ${info.needs.filter(
                k => !keys.has(k)).join(', ')}"`;
        html +=
            `<button class="pf-v6-c-button pf-m-secondary"` +
            `${disabled}${title}` +
            ` onclick="rerunStep('${step}')">` +
            `Re-run ${info.label}</button>`;
    }
    container.innerHTML = html;
}

async function rerunStep(step) {
    if (!devRunId) return;
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Starting...';
    try {
        const resp = await fetch(
            '/api/dev/runs/' + devRunId + '/rerun/' + step,
            {method: 'POST'});
        const data = await resp.json();
        if (resp.ok) {
            showToast(
                'Re-run started: <b>' + data.workflow_id +
                '</b> <a href="' + data.temporal_ui_url +
                '" target="_blank">Open in Temporal</a>',
                'success');
        } else {
            showToast('Error: ' +
                (data.detail || JSON.stringify(data)), 'error');
        }
    } catch (err) {
        showToast('Network error: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent =
            'Re-run ' + RERUN_STEPS[step].label;
    }
}

function showToast(msg, type) {
    const el = document.getElementById('toast');
    const pfType = type === 'success'
        ? 'pf-m-success' : 'pf-m-danger';
    el.className =
        'sdlc-toast pf-v6-c-alert pf-m-inline ' +
        pfType + ' show';
    el.innerHTML =
        '<div class="pf-v6-c-alert__title">' + msg + '</div>';
    setTimeout(() => { el.className = 'sdlc-toast'; }, 6000);
}

loadRuns();
loadPrompts().then(() => initMonaco());
"""


def render_dev_page(external_urls: dict[str, str]) -> str:
    sidebar_links_html = ""
    link_items = [
        ("Temporal UI",
         external_urls.get("Temporal UI", "http://localhost:8233")),
        ("RustFS Console",
         external_urls.get("RustFS (S3)", "http://localhost:9001")),
        ("Gitea",
         external_urls.get("Gitea", "http://localhost:3000")),
        ("Jira Simulator",
         external_urls.get("Jira Simulator", "http://localhost:8080")),
    ]
    for label, url in link_items:
        sidebar_links_html += (
            f'<li><a href="{url}" target="_blank">'
            f'{label}</a></li>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en" class="pf-v6-theme-dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
        content="width=device-width, initial-scale=1.0">
    <title>Developer — SDLC Dashboard</title>
    <link rel="stylesheet" href="{_PF_CSS_CDN}">
    <style>{_CSS}
{_DEV_CSS}</style>
</head>
<body>
<div class="pf-v6-c-page">

    <header class="pf-v6-c-masthead">
        <div class="pf-v6-c-masthead__main">
            <span class="pf-v6-c-masthead__brand">
                SDLC Workflow Dashboard
            </span>
        </div>
    </header>

    <div class="pf-v6-c-page__sidebar pf-m-expanded">
        <div class="pf-v6-c-page__sidebar-body">

            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Navigation
                </h3>
                <ul class="sdlc-sidebar-links">
                    <li><a href="/">Dashboard</a></li>
                    <li><a href="/settings">
                        Settings</a></li>
                    <li><a href="/status">
                        Service Status</a></li>
                    <li><span class="sub-label">
                        Developer</span></li>
                    <li class="sub"><a href="/dev">
                        Editor</a></li>
                    <li class="sub"><a href="/dev/tokens">
                        Token Usage</a></li>
                </ul>
            </div>

            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Quick Links
                </h3>
                <ul class="sdlc-sidebar-links">
                    {sidebar_links_html}
                </ul>
            </div>

        </div>
    </div>

    <main class="pf-v6-c-page__main" tabindex="-1">
    <section class="pf-v6-c-page__main-section">

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">
                Developer Tools
            </h2>
            <p style="color:#94a3b8;margin-bottom:16px;
                max-width:700px;font-size:0.9rem">
                Edit prompt templates and workflow artifacts.
                Select a workflow run to view and modify its
                S3 artifacts, or browse the prompt templates
                that control LLM behavior. Changes to prompts
                take effect immediately on the next LLM call.
            </p>
            <div class="pf-v6-c-form__group"
                style="max-width: 400px; margin-bottom: 16px">
                <label class="pf-v6-c-form__label"
                    for="dev-run-select">
                    <span class="pf-v6-c-form__label-text">
                        Workflow Run
                    </span>
                </label>
                <span class="pf-v6-c-form-control">
                    <select id="dev-run-select"
                        onchange="selectRun(this.value)">
                        <option value="">
                            Select a run
                        </option>
                    </select>
                </span>
            </div>
        </div>

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">
                Re-run Step
            </h2>
            <div id="dev-rerun" class="sdlc-rerun-bar">
                <em>Select a run to see available steps</em>
            </div>
        </div>

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">
                Editor
            </h2>
            <div class="sdlc-editor">
                <div class="sdlc-editor-sidebar"
                    id="editor-file-list">
                    <div style="padding:12px;color:#94a3b8">
                        Loading...
                    </div>
                </div>
                <div class="sdlc-editor-main">
                    <div class="sdlc-editor-tab">
                        <span class="tab-name"
                            id="editor-tab-name">
                            No file selected
                        </span>
                        <button
                          class="pf-v6-c-button pf-m-primary
                            pf-m-small"
                          onclick="saveCurrentFile()">
                            Save
                        </button>
                    </div>
                    <div class="sdlc-editor-content"
                        id="editor-container">
                    </div>
                    <div class="sdlc-editor-status">
                        <span id="editor-status-text">
                            Ready
                        </span>
                        <span style="font-size:0.75rem">
                            Ctrl+S to save
                        </span>
                    </div>
                </div>
            </div>
        </div>

    </section>
    </main>

</div>

<div id="toast" class="sdlc-toast"></div>
<script
    src="https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/loader.js"
    integrity="sha384-pHG02SG8pId94Np3AbPmBEJ1yPqaH0IkJGLSNGXYmuGhkazT8Lr/57WYpbkGjJtu"
    crossorigin="anonymous"></script>
<script>{_DEV_JS}</script>
</body>
</html>"""


_TOKENS_JS = """
async function loadRuns() {
    try {
        const resp = await fetch('/api/workflows');
        const data = await resp.json();
        const sel = document.getElementById('tokens-run-select');
        const seen = new Set();
        for (const w of data.workflows) {
            if (seen.has(w.run_id)) continue;
            seen.add(w.run_id);
            const opt = document.createElement('option');
            opt.value = w.run_id;
            opt.textContent =
                w.run_id + ' (' + w.task_type_label + ')';
            sel.appendChild(opt);
        }
    } catch (err) {
        console.error('Failed to load runs:', err);
    }
}

async function selectTokenRun(runId) {
    const container = document.getElementById('tokens-table');
    if (!runId) {
        container.innerHTML = '<em>Select a run above</em>';
        return;
    }
    try {
        const resp = await fetch(
            '/api/dev/runs/' + runId + '/tokens');
        const data = await resp.json();
        renderTokens(data.records);
    } catch (err) {
        container.innerHTML =
            '<em>Failed to load token data</em>';
    }
}

function renderTokens(records) {
    const container = document.getElementById('tokens-table');
    if (!records || records.length === 0) {
        container.innerHTML =
            '<em>No token usage recorded for this run</em>';
        return;
    }
    let totPrompt = 0, totCompletion = 0, totTotal = 0;
    let rows = '';
    for (const r of records) {
        totPrompt += r.prompt_tokens;
        totCompletion += r.completion_tokens;
        totTotal += r.total_tokens;
        rows += `<tr role="row">` +
            `<td role="gridcell">${r.step}</td>` +
            `<td role="gridcell">${r.model}</td>` +
            `<td role="gridcell">${r.prompt_tokens.toLocaleString()}</td>` +
            `<td role="gridcell">${r.completion_tokens.toLocaleString()}</td>` +
            `<td role="gridcell">${r.total_tokens.toLocaleString()}</td>` +
            `<td role="gridcell">${r.timestamp.substring(11, 19)}</td>` +
            `</tr>`;
    }
    rows += `<tr role="row" style="font-weight:700;` +
        `border-top:2px solid #475569">` +
        `<td role="gridcell">Total (${records.length} calls)</td>` +
        `<td role="gridcell"></td>` +
        `<td role="gridcell">${totPrompt.toLocaleString()}</td>` +
        `<td role="gridcell">${totCompletion.toLocaleString()}</td>` +
        `<td role="gridcell">${totTotal.toLocaleString()}</td>` +
        `<td role="gridcell"></td></tr>`;
    container.innerHTML =
        `<table class="pf-v6-c-table pf-m-compact"` +
        ` role="grid" aria-label="Token usage">` +
        `<thead><tr role="row">` +
        `<th role="columnheader">Step</th>` +
        `<th role="columnheader">Model</th>` +
        `<th role="columnheader">Prompt</th>` +
        `<th role="columnheader">Completion</th>` +
        `<th role="columnheader">Total</th>` +
        `<th role="columnheader">Time</th>` +
        `</tr></thead><tbody>` + rows + `</tbody></table>`;
}

loadRuns();
"""


def render_tokens_page(external_urls: dict[str, str]) -> str:
    sidebar_links_html = ""
    link_items = [
        ("Temporal UI",
         external_urls.get("Temporal UI", "http://localhost:8233")),
        ("RustFS Console",
         external_urls.get("RustFS (S3)", "http://localhost:9001")),
        ("Gitea",
         external_urls.get("Gitea", "http://localhost:3000")),
        ("Jira Simulator",
         external_urls.get("Jira Simulator", "http://localhost:8080")),
    ]
    for label, url in link_items:
        sidebar_links_html += (
            f'<li><a href="{url}" target="_blank">'
            f'{label}</a></li>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en" class="pf-v6-theme-dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
        content="width=device-width, initial-scale=1.0">
    <title>Token Usage — SDLC Dashboard</title>
    <link rel="stylesheet" href="{_PF_CSS_CDN}">
    <style>{_CSS}</style>
</head>
<body>
<div class="pf-v6-c-page">

    <header class="pf-v6-c-masthead">
        <div class="pf-v6-c-masthead__main">
            <span class="pf-v6-c-masthead__brand">
                SDLC Workflow Dashboard
            </span>
        </div>
    </header>

    <div class="pf-v6-c-page__sidebar pf-m-expanded">
        <div class="pf-v6-c-page__sidebar-body">
            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Navigation
                </h3>
                <ul class="sdlc-sidebar-links">
                    <li><a href="/">Dashboard</a></li>
                    <li><a href="/settings">
                        Settings</a></li>
                    <li><a href="/status">
                        Service Status</a></li>
                    <li><span class="sub-label">
                        Developer</span></li>
                    <li class="sub"><a href="/dev">
                        Editor</a></li>
                    <li class="sub"><a href="/dev/tokens">
                        Token Usage</a></li>
                </ul>
            </div>
            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Quick Links
                </h3>
                <ul class="sdlc-sidebar-links">
                    {sidebar_links_html}
                </ul>
            </div>
        </div>
    </div>

    <main class="pf-v6-c-page__main" tabindex="-1">
    <section class="pf-v6-c-page__main-section">

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">
                Token Usage
            </h2>
            <p style="color:#94a3b8;margin-bottom:16px;
                max-width:700px;font-size:0.9rem">
                Track LLM token consumption by workflow step
                and model. Select a workflow run to see a
                breakdown of prompt, completion, and total
                tokens for each activity.
            </p>
            <div class="pf-v6-c-form__group"
                style="max-width: 400px; margin-bottom: 16px">
                <label class="pf-v6-c-form__label"
                    for="tokens-run-select">
                    <span class="pf-v6-c-form__label-text">
                        Workflow Run
                    </span>
                </label>
                <span class="pf-v6-c-form-control">
                    <select id="tokens-run-select"
                        onchange="selectTokenRun(this.value)">
                        <option value="">Select a run</option>
                    </select>
                </span>
            </div>
            <div id="tokens-table">
                <em>Select a run above</em>
            </div>
        </div>

    </section>
    </main>

</div>

<script>{_TOKENS_JS}</script>
</body>
</html>"""


_CONTEXT_JS = """
async function loadRuns() {
    try {
        const resp = await fetch('/api/workflows');
        const data = await resp.json();
        const sel = document.getElementById('ctx-run-select');
        const seen = new Set();
        for (const w of data.workflows) {
            if (seen.has(w.run_id)) continue;
            seen.add(w.run_id);
            const opt = document.createElement('option');
            opt.value = w.run_id;
            opt.textContent =
                w.run_id + ' (' + w.task_type_label + ')';
            sel.appendChild(opt);
        }
    } catch (err) {
        console.error('Failed to load runs:', err);
    }
}

let ctxArtifacts = [];

async function selectCtxRun(runId) {
    const container = document.getElementById('ctx-content');
    if (!runId) {
        container.innerHTML = '<em>Select a run above</em>';
        return;
    }
    try {
        const resp = await fetch(
            '/api/dev/runs/' + runId + '/artifacts');
        const data = await resp.json();
        ctxArtifacts = data.artifacts || [];
        renderCtxList();
    } catch (err) {
        container.innerHTML =
            '<em>Failed to load artifacts</em>';
    }
}

function renderCtxList() {
    const container = document.getElementById('ctx-content');
    if (ctxArtifacts.length === 0) {
        container.innerHTML =
            '<em>No artifacts found for this run</em>';
        return;
    }
    let html = '';
    for (let i = 0; i < ctxArtifacts.length; i++) {
        const a = ctxArtifacts[i];
        html +=
            `<div style="border:1px solid #334155;` +
            `border-radius:6px;margin-bottom:8px;` +
            `overflow:hidden">` +
            `<div style="padding:8px 14px;cursor:pointer;` +
            `display:flex;justify-content:space-between"` +
            ` onclick="toggleCtx(${i})">` +
            `<span style="font-weight:600;` +
            `font-size:0.9rem">${a.key}</span>` +
            `</div>` +
            `<div id="ctx-body-${i}" style="display:none;` +
            `border-top:1px solid #334155;` +
            `max-height:500px;overflow:auto">` +
            `<pre style="margin:0;padding:12px 14px;` +
            `font-size:0.8rem;line-height:1.4;` +
            `white-space:pre-wrap;word-break:break-word">` +
            `${escHtml(JSON.stringify(a.data, null, 2))}` +
            `</pre></div></div>`;
    }
    container.innerHTML = html;
}

function toggleCtx(idx) {
    const el = document.getElementById('ctx-body-' + idx);
    if (!el) return;
    el.style.display =
        el.style.display === 'block' ? 'none' : 'block';
}

function escHtml(s) {
    return s.replace(/&/g, '&amp;')
        .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

loadRuns();
"""


def render_context_page(external_urls: dict[str, str]) -> str:
    sidebar_links_html = ""
    link_items = [
        ("Temporal UI",
         external_urls.get("Temporal UI", "http://localhost:8233")),
        ("RustFS Console",
         external_urls.get("RustFS (S3)", "http://localhost:9001")),
        ("Gitea",
         external_urls.get("Gitea", "http://localhost:3000")),
        ("Jira Simulator",
         external_urls.get("Jira Simulator", "http://localhost:8080")),
    ]
    for label, url in link_items:
        sidebar_links_html += (
            f'<li><a href="{url}" target="_blank">'
            f'{label}</a></li>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en" class="pf-v6-theme-dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
        content="width=device-width, initial-scale=1.0">
    <title>Context — SDLC Dashboard</title>
    <link rel="stylesheet" href="{_PF_CSS_CDN}">
    <style>{_CSS}</style>
</head>
<body>
<div class="pf-v6-c-page">

    <header class="pf-v6-c-masthead">
        <div class="pf-v6-c-masthead__main">
            <span class="pf-v6-c-masthead__brand">
                SDLC Workflow Dashboard
            </span>
        </div>
    </header>

    <div class="pf-v6-c-page__sidebar pf-m-expanded">
        <div class="pf-v6-c-page__sidebar-body">
            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Navigation
                </h3>
                <ul class="sdlc-sidebar-links">
                    <li><a href="/">Dashboard</a></li>
                    <li><a href="/settings">
                        Settings</a></li>
                    <li><a href="/status">
                        Service Status</a></li>
                    <li><span class="sub-label">
                        Developer</span></li>
                    <li class="sub"><a href="/dev">
                        Editor</a></li>
                    <li class="sub"><a href="/dev/tokens">
                        Token Usage</a></li>
                </ul>
            </div>
            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Quick Links
                </h3>
                <ul class="sdlc-sidebar-links">
                    {sidebar_links_html}
                </ul>
            </div>
        </div>
    </div>

    <main class="pf-v6-c-page__main" tabindex="-1">
    <section class="pf-v6-c-page__main-section">

        <div class="sdlc-section">
            <h2 class="pf-v6-c-title pf-m-lg">
                Workflow Context
            </h2>
            <div class="pf-v6-c-form__group"
                style="max-width: 400px; margin-bottom: 16px">
                <label class="pf-v6-c-form__label"
                    for="ctx-run-select">
                    <span class="pf-v6-c-form__label-text">
                        Workflow Run
                    </span>
                </label>
                <span class="pf-v6-c-form-control">
                    <select id="ctx-run-select"
                        onchange="selectCtxRun(this.value)">
                        <option value="">Select a run</option>
                    </select>
                </span>
            </div>
            <div id="ctx-content">
                <em>Select a run to view step contexts</em>
            </div>
        </div>

    </section>
    </main>

</div>

<script>{_CONTEXT_JS}</script>
</body>
</html>"""


_SETTINGS_CSS = """
.sdlc-settings-form {
    max-width: 900px;
}
.sdlc-agent-card {
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 16px;
    margin-bottom: 12px;
}
.sdlc-agent-card h4 {
    margin: 0 0 4px 0; font-size: 0.95rem;
}
.sdlc-agent-card .agent-desc {
    font-size: 0.8rem; color: #94a3b8;
    margin-bottom: 12px;
}
.sdlc-agent-fields {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}
.sdlc-settings-banner {
    padding: 12px 16px; border-radius: 6px;
    margin-bottom: 16px; display: none;
}
.sdlc-settings-banner.show { display: block; }
.sdlc-settings-banner.pf-m-warning {
    background: rgba(240,171,0,.12);
    border: 1px solid #f0ab00;
    color: #f0ab00;
}
.sdlc-settings-banner.pf-m-success {
    background: rgba(34,197,94,.1);
    border: 1px solid #22c55e;
    color: #22c55e;
}
.sdlc-model-hint {
    font-size: 0.78rem; color: #94a3b8;
    margin-bottom: 16px; line-height: 1.5;
}
.sdlc-model-hint code {
    background: rgba(255,255,255,.06);
    padding: 1px 5px; border-radius: 3px;
}
"""

_SETTINGS_JS = """
const AGENTS = [
    {key: 'orchestrator', name: 'Orchestrator',
     desc: 'Routes tasks to other agents; typically no LLM calls.'},
    {key: 'requirements-agent', name: 'Requirements Agent',
     desc: 'Fetches Jira epics and produces requirement specs.'},
    {key: 'github-agent', name: 'GitHub Agent',
     desc: 'Analyzes PRs, generates code, manages branches.'},
    {key: 'enhancement-agent', name: 'Enhancement Agent',
     desc: 'Generates enhancement documents and PR lifecycle.'},
    {key: 'openshift-agent', name: 'OpenShift Agent',
     desc: 'Identifies repos, analyzes features, CI requirements.'},
    {key: 'jira-agent', name: 'Jira Agent',
     desc: 'Proposes, sizes, and prioritizes Jira stories.'},
];

let llmConfig = {default: {}, agents: {}};

async function loadLLMConfig() {
    try {
        const resp = await fetch('/api/settings/llm');
        llmConfig = await resp.json();
        populateForm();
    } catch (err) {
        console.error('Failed to load LLM config:', err);
    }
}

function populateForm() {
    const d = llmConfig.default || {};
    setVal('default-model', d.model);
    setVal('default-api-base', d.api_base);
    setVal('default-vertex-project', d.vertex_project);
    setVal('default-vertex-location', d.vertex_location);

    for (const agent of AGENTS) {
        const cfg = (llmConfig.agents || {})[agent.key] || {};
        setVal(agent.key + '-model', cfg.model);
        setVal(agent.key + '-api-base', cfg.api_base);
    }
}

function setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val || '';
}

function getVal(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
}

async function saveLLMConfig() {
    const btn = document.getElementById('btn-save-llm');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    const payload = {
        default: {
            model: getVal('default-model') || '',
            api_key: (llmConfig.default || {}).api_key || '',
            api_base: getVal('default-api-base') || null,
            vertex_project: getVal('default-vertex-project') || null,
            vertex_location: getVal('default-vertex-location') || null,
        },
        agents: {},
    };

    for (const agent of AGENTS) {
        const existing = (llmConfig.agents || {})[agent.key] || {};
        payload.agents[agent.key] = {
            model: getVal(agent.key + '-model') || '',
            api_key: existing.api_key || '',
            api_base: getVal(agent.key + '-api-base') || null,
        };
    }

    try {
        const resp = await fetch('/api/settings/llm', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (resp.ok) {
            showBanner('success',
                'Configuration saved. Restart workers to apply.');
            loadLLMConfig();
        } else {
            showBanner('warning',
                'Error: ' + (data.detail || 'save failed'));
        }
    } catch (err) {
        showBanner('warning', 'Network error: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Save Configuration';
    }
}

function showBanner(type, msg) {
    const el = document.getElementById('settings-banner');
    el.className = 'sdlc-settings-banner show pf-m-' + type;
    el.textContent = msg;
}

loadLLMConfig();
"""


def render_settings_page(external_urls: dict[str, str]) -> str:
    sidebar_links_html = ""
    link_items = [
        ("Temporal UI",
         external_urls.get("Temporal UI", "http://localhost:8233")),
        ("RustFS Console",
         external_urls.get("RustFS (S3)", "http://localhost:9001")),
        ("Gitea",
         external_urls.get("Gitea", "http://localhost:3000")),
        ("Jira Simulator",
         external_urls.get("Jira Simulator", "http://localhost:8080")),
    ]
    for label, url in link_items:
        sidebar_links_html += (
            f'<li><a href="{url}" target="_blank">'
            f'{label}</a></li>\n'
        )

    agent_cards = ""
    agents = [
        ("orchestrator", "Orchestrator",
         "Routes tasks to other agents; typically no LLM calls."),
        ("requirements-agent", "Requirements Agent",
         "Fetches Jira epics and produces requirement specs."),
        ("github-agent", "GitHub Agent",
         "Analyzes PRs, generates code, manages branches."),
        ("enhancement-agent", "Enhancement Agent",
         "Generates enhancement documents and PR lifecycle."),
        ("openshift-agent", "OpenShift Agent",
         "Identifies repos, analyzes features, CI requirements."),
        ("jira-agent", "Jira Agent",
         "Proposes, sizes, and prioritizes Jira stories."),
    ]
    for key, name, desc in agents:
        agent_cards += f"""
            <div class="sdlc-agent-card">
                <h4>{name}</h4>
                <div class="agent-desc">{desc}</div>
                <div class="sdlc-agent-fields">
                    <div class="pf-v6-c-form__group">
                        <label class="pf-v6-c-form__label"
                            for="{key}-model">
                            <span class="pf-v6-c-form__label-text">
                                Model</span></label>
                        <span class="pf-v6-c-form-control">
                            <input type="text" id="{key}-model"
                                placeholder="inherits from default">
                        </span>
                    </div>
                    <div class="pf-v6-c-form__group">
                        <label class="pf-v6-c-form__label"
                            for="{key}-api-base">
                            <span class="pf-v6-c-form__label-text">
                                API Base URL</span></label>
                        <span class="pf-v6-c-form-control">
                            <input type="text" id="{key}-api-base"
                                placeholder="inherits from default">
                        </span>
                    </div>
                </div>
            </div>"""

    return f"""<!DOCTYPE html>
<html lang="en" class="pf-v6-theme-dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport"
        content="width=device-width, initial-scale=1.0">
    <title>Settings — SDLC Dashboard</title>
    <link rel="stylesheet" href="{_PF_CSS_CDN}">
    <style>{_CSS}
{_SETTINGS_CSS}</style>
</head>
<body>
<div class="pf-v6-c-page">

    <header class="pf-v6-c-masthead">
        <div class="pf-v6-c-masthead__main">
            <span class="pf-v6-c-masthead__brand">
                SDLC Workflow Dashboard
            </span>
        </div>
    </header>

    <div class="pf-v6-c-page__sidebar pf-m-expanded">
        <div class="pf-v6-c-page__sidebar-body">
            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Navigation
                </h3>
                <ul class="sdlc-sidebar-links">
                    <li><a href="/">Dashboard</a></li>
                    <li><a href="/settings">Settings</a></li>
                    <li><a href="/status">
                        Service Status</a></li>
                    <li><span class="sub-label">
                        Developer</span></li>
                    <li class="sub"><a href="/dev">
                        Editor</a></li>
                    <li class="sub"><a href="/dev/tokens">
                        Token Usage</a></li>
                </ul>
            </div>
            <div class="sdlc-sidebar-section">
                <h3 class="pf-v6-c-title pf-m-md"
                    style="padding: 16px 16px 8px">
                    Quick Links
                </h3>
                <ul class="sdlc-sidebar-links">
                    {sidebar_links_html}
                </ul>
            </div>
        </div>
    </div>

    <main class="pf-v6-c-page__main" tabindex="-1">
    <section class="pf-v6-c-page__main-section">

        <div class="sdlc-section sdlc-settings-form">
            <h2 class="pf-v6-c-title pf-m-lg">
                LLM Configuration
            </h2>
            <div class="sdlc-model-hint">
                Model strings follow LiteLLM format:
                <code>ollama/model</code>
                <code>openai/model</code>
                <code>anthropic/model</code>
                <code>vertex_ai/model</code>
                &mdash; leave blank to inherit from environment
                variables.
            </div>

            <div id="settings-banner"
                class="sdlc-settings-banner"></div>

            <h3 class="pf-v6-c-title pf-m-md"
                style="margin-bottom:12px">
                Defaults
            </h3>
            <div class="sdlc-agent-card">
                <div class="sdlc-agent-fields">
                    <div class="pf-v6-c-form__group">
                        <label class="pf-v6-c-form__label"
                            for="default-model">
                            <span class="pf-v6-c-form__label-text">
                                Model</span></label>
                        <span class="pf-v6-c-form-control">
                            <input type="text"
                                id="default-model"
                                placeholder="openai/gpt-4o">
                        </span>
                    </div>
                    <div class="pf-v6-c-form__group">
                        <label class="pf-v6-c-form__label"
                            for="default-api-base">
                            <span class="pf-v6-c-form__label-text">
                                API Base URL</span></label>
                        <span class="pf-v6-c-form-control">
                            <input type="text"
                                id="default-api-base"
                                placeholder="from LLM_API_BASE env">
                        </span>
                    </div>
                    <div class="pf-v6-c-form__group">
                        <label class="pf-v6-c-form__label"
                            for="default-vertex-project">
                            <span class="pf-v6-c-form__label-text">
                                Vertex Project</span></label>
                        <span class="pf-v6-c-form-control">
                            <input type="text"
                                id="default-vertex-project"
                                placeholder="my-gcp-project">
                        </span>
                    </div>
                    <div class="pf-v6-c-form__group">
                        <label class="pf-v6-c-form__label"
                            for="default-vertex-location">
                            <span class="pf-v6-c-form__label-text">
                                Vertex Location</span></label>
                        <span class="pf-v6-c-form-control">
                            <input type="text"
                                id="default-vertex-location"
                                placeholder="us-central1">
                        </span>
                    </div>
                </div>
            </div>

            <h3 class="pf-v6-c-title pf-m-md"
                style="margin: 20px 0 12px">
                Per-Agent Overrides
            </h3>
            {agent_cards}

            <div style="margin-top: 16px">
                <button id="btn-save-llm"
                    class="pf-v6-c-button pf-m-primary"
                    onclick="saveLLMConfig()">
                    Save Configuration
                </button>
            </div>
        </div>

    </section>
    </main>

</div>

<script>{_SETTINGS_JS}</script>
</body>
</html>"""
