"""
Minimal Jira REST API simulator.

Implements exactly the endpoints used by this project's jira_client.py and
jira_write_client.py. Data is stored in SQLite so it survives container restarts.

Endpoints:
  GET  /rest/api/2/serverInfo
  GET  /rest/api/2/myself
  GET  /rest/api/2/issueLinkType
  GET  /rest/api/2/issue/{key}
  GET  /rest/api/2/search
  POST /rest/api/2/issue
  PUT  /rest/api/2/issue/{key}
  POST /rest/api/2/issueLink
  POST /rest/api/2/issue/{key}/comment
  GET  /rest/api/2/issue/{key}/comment
  GET  /rest/api/2/issue/{key}/transitions
  POST /rest/api/2/issue/{key}/transitions

UI:
  GET  /ui             — list all issues
  GET  /ui/issue/{key} — issue detail with comments and links
  GET  /docs           — FastAPI Swagger UI (auto-generated)
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from typing import Any

import html as _html

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "").strip().upper()
if not PROJECT_KEY:
    sys.exit("JIRA_PROJECT_KEY environment variable is required (e.g. JIRA_PROJECT_KEY=SDLC)")

DB_PATH = os.environ.get("JIRA_DB_PATH", "/data/jira.db")

# ── Database ──────────────────────────────────────────────────────────────────

def _init_db(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS counters (
                project TEXT PRIMARY KEY,
                next_number INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS issues (
                key         TEXT PRIMARY KEY,
                project     TEXT NOT NULL,
                number      INTEGER NOT NULL,
                summary     TEXT NOT NULL DEFAULT '',
                description TEXT,
                issuetype   TEXT NOT NULL DEFAULT 'Story',
                status      TEXT NOT NULL DEFAULT 'To Do',
                resolution  TEXT,
                story_points REAL,
                epic_link_key TEXT,
                parent_key  TEXT,
                labels      TEXT NOT NULL DEFAULT '[]',
                fix_versions TEXT NOT NULL DEFAULT '[]',
                created_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS comments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_key   TEXT NOT NULL,
                body        TEXT NOT NULL DEFAULT '',
                author      TEXT NOT NULL DEFAULT 'Simulator',
                created_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS issue_links (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                type_name   TEXT NOT NULL,
                outward_key TEXT NOT NULL,
                inward_key  TEXT NOT NULL
            );
        """)
        # Migrate existing databases that predate the labels column.
        try:
            conn.execute("ALTER TABLE issues ADD COLUMN labels TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE issues ADD COLUMN fix_versions TEXT NOT NULL DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass  # column already exists

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def _next_key(project: str) -> str:
    with db() as conn:
        conn.execute(
            "INSERT INTO counters(project, next_number) VALUES(?,1) ON CONFLICT(project) DO NOTHING",
            (project,),
        )
        row = conn.execute("SELECT next_number FROM counters WHERE project=?", (project,)).fetchone()
        n = row["next_number"]
        conn.execute("UPDATE counters SET next_number=? WHERE project=?", (n + 1, project))
    return f"{project}-{n}"

# ── Issue serialisation ───────────────────────────────────────────────────────

def _fmt_ts(ts: float) -> str:
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S.000+0000")

def _issue_row_to_dict(row: sqlite3.Row, conn: sqlite3.Connection, include_comments: bool = True) -> dict:
    key = row["key"]

    links = conn.execute(
        "SELECT * FROM issue_links WHERE outward_key=? OR inward_key=?", (key, key)
    ).fetchall()
    issue_links_json = []
    for lnk in links:
        if lnk["outward_key"] == key:
            issue_links_json.append({
                "type": {"name": lnk["type_name"], "outward": lnk["type_name"], "inward": lnk["type_name"]},
                "outwardIssue": {"key": lnk["outward_key"], "fields": {"summary": "", "status": {"name": "To Do"}}},
            })
        else:
            issue_links_json.append({
                "type": {"name": lnk["type_name"], "outward": lnk["type_name"], "inward": lnk["type_name"]},
                "inwardIssue": {"key": lnk["inward_key"], "fields": {"summary": "", "status": {"name": "To Do"}}},
            })

    comments_json: list[dict] = []
    if include_comments:
        crows = conn.execute(
            "SELECT * FROM comments WHERE issue_key=? ORDER BY created_at", (key,)
        ).fetchall()
        comments_json = [_comment_row_to_dict(c) for c in crows]

    parent_json = None
    if row["parent_key"]:
        prow = conn.execute("SELECT * FROM issues WHERE key=?", (row["parent_key"],)).fetchone()
        if prow:
            parent_json = {
                "key": prow["key"],
                "fields": {"summary": prow["summary"], "status": {"name": prow["status"]}},
            }

    return {
        "id": str(hash(key) & 0x7FFFFFFF),
        "key": key,
        "self": f"http://localhost:8080/rest/api/2/issue/{key}",
        "fields": {
            "project": {"key": row["project"], "name": row["project"]},
            "summary": row["summary"],
            "description": row["description"],
            "issuetype": {"name": row["issuetype"]},
            "status": {"name": row["status"]},
            "resolution": {"name": row["resolution"]} if row["resolution"] else None,
            "story_points": row["story_points"],
            "customfield_10016": row["story_points"],
            "customfield_10014": row["epic_link_key"],
            "labels": json.loads(row["labels"] or "[]"),
            "fixVersions": [{"name": n} for n in json.loads(row["fix_versions"] or "[]")],
            "parent": parent_json,
            "issuelinks": issue_links_json,
            "comment": {"comments": comments_json, "total": len(comments_json)},
        },
    }

def _comment_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": str(row["id"]),
        "body": row["body"],
        "author": {"displayName": row["author"], "name": row["author"]},
        "created": _fmt_ts(row["created_at"]),
    }

# ── JQL evaluator ─────────────────────────────────────────────────────────────

def _strip_quotes(val: str) -> str:
    val = val.strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    return val

def _eval_jql(jql: str, conn: sqlite3.Connection) -> list[dict]:
    """
    Handles the two JQL patterns this project sends:

      1. "Epic Link" = KEY OR "parent" = KEY
         → epic_link_key = KEY OR parent_key = KEY

      2. project = "P" AND summary ~ "title" AND issuetype = Type
         → project match + fuzzy summary + type match
    """
    jql = jql.strip()

    # Pattern 1: Epic children lookup
    m = re.search(
        r'"Epic Link"\s*=\s*([^\s]+)\s+OR\s+"parent"\s*=\s*([^\s]+)',
        jql, re.IGNORECASE
    )
    if m:
        key1 = _strip_quotes(m.group(1))
        key2 = _strip_quotes(m.group(2))
        rows = conn.execute(
            "SELECT * FROM issues WHERE epic_link_key=? OR parent_key=?", (key1, key2)
        ).fetchall()
        return [_issue_row_to_dict(r, conn) for r in rows]

    # Pattern 2: general field matching
    project_match = re.search(r'project\s*=\s*"?([^"\s]+)"?', jql, re.IGNORECASE)
    summary_match = re.search(r'summary\s*~\s*"([^"]+)"', jql, re.IGNORECASE)
    type_match = re.search(r'issuetype\s*=\s*"?([^"\s]+)"?', jql, re.IGNORECASE)
    # labels = "foo"  OR  labels in ("foo", "bar")
    label_eq = re.search(r'labels\s*=\s*"([^"]+)"', jql, re.IGNORECASE)
    label_in = re.search(r'labels\s+in\s*\(([^)]+)\)', jql, re.IGNORECASE)

    clauses = "1=1"
    params: list[Any] = []

    if project_match:
        clauses += " AND project=?"
        params.append(project_match.group(1).upper())
    if summary_match:
        clauses += " AND summary LIKE ?"
        params.append(f"%{summary_match.group(1)}%")
    if type_match:
        clauses += " AND issuetype=?"
        params.append(type_match.group(1).title())
    if label_eq:
        label_val = label_eq.group(1)
        clauses += " AND EXISTS (SELECT 1 FROM json_each(labels) WHERE value=?)"
        params.append(label_val)
    elif label_in:
        raw = label_in.group(1)
        wanted = [_strip_quotes(v.strip()) for v in raw.split(",")]
        placeholders = ",".join("?" * len(wanted))
        clauses += f" AND EXISTS (SELECT 1 FROM json_each(labels) WHERE value IN ({placeholders}))"
        params.extend(wanted)

    rows = conn.execute(f"SELECT * FROM issues WHERE {clauses}", params).fetchall()
    return [_issue_row_to_dict(r, conn) for r in rows]

# ── Transitions ───────────────────────────────────────────────────────────────

TRANSITIONS = [
    {"id": "11", "name": "In Progress", "to": {"name": "In Progress"}},
    {"id": "21", "name": "Done",        "to": {"name": "Done"}},
    {"id": "31", "name": "Won't Do",    "to": {"name": "Won't Do"}},
]

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Jira Simulator", version="1.0.0")

@app.on_event("startup")
def startup():
    _init_db(DB_PATH)

# ── Jira REST API ─────────────────────────────────────────────────────────────

@app.get("/rest/api/2/serverInfo")
def server_info():
    return {
        "baseUrl": "http://localhost:8080",
        "version": "9.0.0",
        "versionNumbers": [9, 0, 0],
        "deploymentType": "Server",
        "buildNumber": 900000,
        "scmInfo": "simulator",
        "serverTitle": "Jira Simulator",
    }

@app.get("/rest/api/2/myself")
def myself():
    return {
        "self": "http://localhost:8080/rest/api/2/myself",
        "key": "simulator",
        "name": "simulator",
        "displayName": "Simulator",
        "emailAddress": "simulator@localhost",
        "active": True,
    }

@app.get("/rest/api/2/field")
def list_fields():
    return [
        {"id": "summary",          "name": "Summary",       "clauseNames": ["summary"],      "custom": False, "orderable": True, "navigable": True, "searchable": True, "schema": {"type": "string", "system": "summary"}},
        {"id": "description",      "name": "Description",   "clauseNames": ["description"],  "custom": False, "orderable": True, "navigable": True, "searchable": True, "schema": {"type": "string", "system": "description"}},
        {"id": "issuetype",        "name": "Issue Type",    "clauseNames": ["issuetype"],     "custom": False, "orderable": True, "navigable": True, "searchable": True, "schema": {"type": "issuetype", "system": "issuetype"}},
        {"id": "status",           "name": "Status",        "clauseNames": ["status"],        "custom": False, "orderable": False,"navigable": True, "searchable": True, "schema": {"type": "status", "system": "status"}},
        {"id": "labels",           "name": "Labels",        "clauseNames": ["labels"],        "custom": False, "orderable": True, "navigable": True, "searchable": True, "schema": {"type": "array", "items": "string", "system": "labels"}},
        {"id": "parent",           "name": "Parent",        "clauseNames": ["parent"],        "custom": False, "orderable": True, "navigable": True, "searchable": True, "schema": {"type": "issuelinks", "system": "parent"}},
        {"id": "comment",          "name": "Comment",       "clauseNames": ["comment"],       "custom": False, "orderable": True, "navigable": False,"searchable": True, "schema": {"type": "comments-page", "system": "comment"}},
        {"id": "issuelinks",       "name": "Linked Issues", "clauseNames": ["issuelinks"],    "custom": False, "orderable": True, "navigable": True, "searchable": False,"schema": {"type": "array", "items": "issuelinks", "system": "issuelinks"}},
        {"id": "customfield_10016","name": "Story Points",  "clauseNames": ["story_points", "cf[10016]"], "custom": True, "orderable": True, "navigable": True, "searchable": True, "schema": {"type": "number", "custom": "com.atlassian.jira.plugin.system.customfieldtypes:float", "customId": 10016}},
        {"id": "customfield_10014","name": "Epic Link",     "clauseNames": ["\"Epic Link\"", "cf[10014]"], "custom": True, "orderable": True, "navigable": True, "searchable": True, "schema": {"type": "string", "custom": "com.pyxis.greenhopper.jira:gh-epic-link", "customId": 10014}},
    ]

@app.get("/rest/api/2/issueLinkType")
def link_types():
    return {
        "issueLinkTypes": [
            {"id": "10001", "name": "Epic-Story",    "inward": "is Epic of",    "outward": "has Epic"},
            {"id": "10002", "name": "blocks",        "inward": "is blocked by", "outward": "blocks"},
            {"id": "10003", "name": "is blocked by", "inward": "blocks",        "outward": "is blocked by"},
            {"id": "10004", "name": "Relates",       "inward": "relates to",    "outward": "relates to"},
        ]
    }

@app.get("/rest/api/2/issue/{key}")
def get_issue(key: str, fields: str = "*all"):
    with db() as conn:
        row = conn.execute("SELECT * FROM issues WHERE key=?", (key.upper(),)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        return _issue_row_to_dict(row, conn)

@app.get("/rest/api/2/search")
def search_issues(jql: str = "", maxResults: int = 50, startAt: int = 0, fields: str = "*all"):
    with db() as conn:
        issues = _eval_jql(jql, conn)
    return {
        "startAt": startAt,
        "maxResults": maxResults,
        "total": len(issues),
        "issues": issues[startAt: startAt + maxResults],
    }

@app.post("/rest/api/2/issue", status_code=201)
async def create_issue(request: Request):
    body = await request.json()
    f = body.get("fields", {})
    issuetype = f.get("issuetype", {}).get("name", "Story").title()
    key = _next_key(PROJECT_KEY)
    number = int(key.split("-")[1])
    raw_labels = f.get("labels", [])
    labels_json = json.dumps(raw_labels if isinstance(raw_labels, list) else [])
    raw_fix_versions = [v.get("name", "") for v in f.get("fixVersions", []) if isinstance(v, dict)]
    fix_versions_json = json.dumps(raw_fix_versions)
    with db() as conn:
        conn.execute(
            """INSERT INTO issues
               (key, project, number, summary, description, issuetype,
                status, story_points, epic_link_key, parent_key, labels, fix_versions, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                key, PROJECT_KEY, number,
                f.get("summary", ""),
                f.get("description"),
                issuetype,
                "To Do",
                f.get("customfield_10016"),
                f.get("customfield_10014"),
                f.get("parent", {}).get("key") if isinstance(f.get("parent"), dict) else None,
                labels_json,
                fix_versions_json,
                time.time(),
            ),
        )
    return {"id": str(abs(hash(key))), "key": key, "self": f"http://localhost:8080/rest/api/2/issue/{key}"}

@app.put("/rest/api/2/issue/{key}", status_code=204)
async def update_issue(key: str, request: Request):
    body = await request.json()
    fields = body.get("fields", {})
    key = key.upper()
    with db() as conn:
        row = conn.execute("SELECT * FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        col_map = {
            "summary": "summary",
            "description": "description",
            "customfield_10016": "story_points",
            "customfield_10014": "epic_link_key",
            "resolution": "resolution",
        }
        for field_name, col_name in col_map.items():
            if field_name in fields:
                val = fields[field_name]
                if field_name == "resolution" and isinstance(val, dict):
                    val = val.get("name")
                conn.execute(f"UPDATE issues SET {col_name}=? WHERE key=?", (val, key))
        if "labels" in fields:
            raw = fields["labels"]
            conn.execute(
                "UPDATE issues SET labels=? WHERE key=?",
                (json.dumps(raw if isinstance(raw, list) else []), key),
            )
        if "fixVersions" in fields:
            raw = fields["fixVersions"]
            names = [v.get("name", "") for v in raw if isinstance(v, dict)]
            conn.execute(
                "UPDATE issues SET fix_versions=? WHERE key=?",
                (json.dumps(names), key),
            )
        update = body.get("update", {})
        if "labels" in update:
            cur_row = conn.execute("SELECT labels FROM issues WHERE key=?", (key,)).fetchone()
            current = set(json.loads(cur_row["labels"] or "[]"))
            for op in update["labels"]:
                if "add" in op:
                    current.add(op["add"])
                if "remove" in op:
                    current.discard(op["remove"])
            conn.execute(
                "UPDATE issues SET labels=? WHERE key=?",
                (json.dumps(sorted(current)), key),
            )
    return Response(status_code=204)

@app.post("/rest/api/2/issueLink", status_code=201)
async def create_issue_link(request: Request):
    body = await request.json()
    type_name = body.get("type", {}).get("name", "Relates")
    outward_key = (body.get("outwardIssue") or {}).get("key", "")
    inward_key = (body.get("inwardIssue") or {}).get("key", "")
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM issue_links WHERE type_name=? AND outward_key=? AND inward_key=?",
            (type_name, outward_key.upper(), inward_key.upper()),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO issue_links(type_name, outward_key, inward_key) VALUES(?,?,?)",
                (type_name, outward_key.upper(), inward_key.upper()),
            )
    return Response(status_code=201)

@app.post("/rest/api/2/issue/{key}/comment", status_code=201)
async def add_comment(key: str, request: Request):
    body = await request.json()
    text = body.get("body", "")
    key = key.upper()
    with db() as conn:
        row = conn.execute("SELECT key FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        ts = time.time()
        cur = conn.execute(
            "INSERT INTO comments(issue_key, body, author, created_at) VALUES(?,?,?,?)",
            (key, text, "Simulator", ts),
        )
        cid = cur.lastrowid
    return {
        "id": str(cid),
        "body": text,
        "author": {"displayName": "Simulator", "name": "simulator"},
        "created": _fmt_ts(ts),
    }

@app.get("/rest/api/2/issue/{key}/comment")
def get_comments(key: str):
    key = key.upper()
    with db() as conn:
        row = conn.execute("SELECT key FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        rows = conn.execute(
            "SELECT * FROM comments WHERE issue_key=? ORDER BY created_at", (key,)
        ).fetchall()
        comments = [_comment_row_to_dict(r) for r in rows]
    return {"comments": comments, "total": len(comments), "startAt": 0, "maxResults": 100}

@app.get("/rest/api/2/issue/{key}/transitions")
def get_transitions(key: str):
    key = key.upper()
    with db() as conn:
        row = conn.execute("SELECT key FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
    return {"transitions": TRANSITIONS}

@app.post("/rest/api/2/issue/{key}/transitions", status_code=204)
async def transition_issue(key: str, request: Request):
    body = await request.json()
    tid = str(body.get("transition", {}).get("id", ""))
    resolution_fields = body.get("fields", {})
    target = next((t for t in TRANSITIONS if t["id"] == tid), None)
    if not target:
        raise HTTPException(status_code=400, detail=f"Unknown transition id: {tid}")
    key = key.upper()
    with db() as conn:
        row = conn.execute("SELECT key FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        new_status = target["to"]["name"]
        resolution = None
        if "resolution" in resolution_fields:
            r = resolution_fields["resolution"]
            resolution = r.get("name") if isinstance(r, dict) else r
        conn.execute(
            "UPDATE issues SET status=?, resolution=? WHERE key=?",
            (new_status, resolution, key),
        )
    return Response(status_code=204)

# ── Admin / import ───────────────────────────────────────────────────────────

@app.post("/api/admin/import")
async def import_issues(request: Request):
    """
    Bulk-import issues with their original Jira keys (bypasses auto-increment).
    Idempotent: issues whose key already exists are skipped.

    Body: {"issues": [{key, summary, description, issuetype, status,
                        resolution, story_points, epic_link_key, parent_key}, ...]}
    Returns: {"imported": N, "skipped": N, "keys": [...]}
    """
    body = await request.json()
    issues = body.get("issues", [])
    force = bool(body.get("force", False))
    imported, skipped_keys = 0, []

    with db() as conn:
        for issue in issues:
            key = str(issue.get("key", "")).strip().upper()
            if not key:
                continue
            exists = conn.execute("SELECT key FROM issues WHERE key=?", (key,)).fetchone()
            if exists and not force:
                skipped_keys.append(key)
                continue
            if exists and force:
                # Update all fields in place.
                raw_labels = issue.get("labels", [])
                raw_fv = issue.get("fix_versions", [])
                conn.execute(
                    """UPDATE issues SET summary=?, description=?, issuetype=?, status=?,
                       resolution=?, story_points=?, epic_link_key=?, parent_key=?, labels=?,
                       fix_versions=?
                       WHERE key=?""",
                    (
                        issue.get("summary", ""),
                        issue.get("description"),
                        (issue.get("issuetype") or "Story").title(),
                        issue.get("status", "To Do"),
                        issue.get("resolution"),
                        issue.get("story_points"),
                        issue.get("epic_link_key"),
                        issue.get("parent_key"),
                        json.dumps(raw_labels if isinstance(raw_labels, list) else []),
                        json.dumps(raw_fv if isinstance(raw_fv, list) else []),
                        key,
                    ),
                )
                imported += 1
                continue

            parts = key.rsplit("-", 1)
            project = parts[0] if len(parts) == 2 else key
            number = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0

            raw_labels = issue.get("labels", [])
            labels_json = json.dumps(raw_labels if isinstance(raw_labels, list) else [])
            raw_fv = issue.get("fix_versions", [])
            fix_versions_json = json.dumps(raw_fv if isinstance(raw_fv, list) else [])
            conn.execute(
                """INSERT INTO issues
                   (key, project, number, summary, description, issuetype,
                    status, resolution, story_points, epic_link_key, parent_key, labels,
                    fix_versions, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    key, project, number,
                    issue.get("summary", ""),
                    issue.get("description"),
                    (issue.get("issuetype") or "Story").title(),
                    issue.get("status", "To Do"),
                    issue.get("resolution"),
                    issue.get("story_points"),
                    issue.get("epic_link_key"),
                    issue.get("parent_key"),
                    labels_json,
                    fix_versions_json,
                    time.time(),
                ),
            )
            # Keep the counter ahead of any imported number so new issues don't collide.
            conn.execute(
                """INSERT INTO counters(project, next_number) VALUES(?,?)
                   ON CONFLICT(project) DO UPDATE SET next_number=MAX(next_number, excluded.next_number)""",
                (project, number + 1),
            )
            imported += 1

    return {"imported": imported, "skipped": len(skipped_keys), "skipped_keys": skipped_keys}

# ── HTML UI ───────────────────────────────────────────────────────────────────

_CSS = """
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a2e; }
  h1 { color: #0052cc; }
  h2 { color: #0052cc; border-bottom: 2px solid #0052cc; padding-bottom: 0.25rem; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 2rem; }
  th { background: #0052cc; color: white; padding: 0.5rem 0.75rem; text-align: left; }
  td { padding: 0.4rem 0.75rem; border-bottom: 1px solid #ddd; }
  tr:hover td { background: #f4f5f7; }
  .key a { font-family: monospace; font-weight: bold; color: #0052cc; text-decoration: none; }
  .key a:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 0.8rem; }
  .todo    { background: #dfe1e6; }
  .inprog  { background: #deebff; color: #0052cc; }
  .done    { background: #e3fcef; color: #006644; }
  .wontdo  { background: #ffd6d6; color: #8b0000; }
  .section { margin-top: 2rem; }
  .meta    { color: #666; font-size: 0.9rem; margin-bottom: 1rem; }
  .comment { background: #f4f5f7; border-left: 3px solid #0052cc; padding: 0.5rem 1rem; margin: 0.5rem 0; }
  .comment .author { font-weight: bold; font-size: 0.85rem; color: #555; }
  .back    { margin-bottom: 1rem; }
  .back a  { color: #0052cc; text-decoration: none; }
  .pts     { font-weight: bold; color: #00875a; }
  .lbl     { display: inline-block; background: #e0e0ff; color: #3333aa; padding: 1px 7px; border-radius: 3px; font-size: 0.8rem; margin: 1px; }
  /* Forms */
  .btn     { display: inline-block; padding: 6px 16px; border: none; border-radius: 3px;
             font-size: 0.9rem; cursor: pointer; text-decoration: none; color: white; }
  .btn-primary { background: #0052cc; }
  .btn-primary:hover { background: #0747a6; }
  .btn-sm  { padding: 4px 10px; font-size: 0.8rem; }
  .btn-green { background: #00875a; }
  .btn-green:hover { background: #006644; }
  form.sim-form label { display: block; font-weight: bold; margin: 0.75rem 0 0.25rem; color: #333; }
  form.sim-form input[type="text"],
  form.sim-form input[type="number"],
  form.sim-form textarea,
  form.sim-form select { width: 100%; max-width: 600px; padding: 6px 8px; border: 1px solid #ccc;
                         border-radius: 3px; font-size: 0.9rem; font-family: inherit; box-sizing: border-box; }
  form.sim-form textarea { min-height: 120px; resize: vertical; }
  form.sim-form .form-actions { margin-top: 1.25rem; }
  .toolbar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 1.5rem; }
  .inline-form { display: inline-flex; gap: 0.5rem; align-items: center; }
  .inline-form select { width: auto; max-width: none; }
</style>
"""

def _status_badge(status: str) -> str:
    cls = {"To Do": "todo", "In Progress": "inprog", "Done": "done", "Won't Do": "wontdo"}.get(status, "todo")
    return f'<span class="badge {cls}">{status}</span>'

@app.get("/ui", response_class=HTMLResponse)
def ui_list():
    with db() as conn:
        epics = conn.execute(
            "SELECT * FROM issues WHERE issuetype='Epic' ORDER BY number"
        ).fetchall()
        stories = conn.execute(
            "SELECT * FROM issues WHERE issuetype='Story' ORDER BY number"
        ).fetchall()
        others = conn.execute(
            "SELECT * FROM issues WHERE issuetype NOT IN ('Epic','Story') ORDER BY number"
        ).fetchall()

    def rows(issues, extra_col: str = "") -> str:
        if not issues:
            return "<tr><td colspan='6' style='color:#888'>No issues yet.</td></tr>"
        out = []
        for r in issues:
            pts = f'<span class="pts">{int(r["story_points"])}</span>' if r["story_points"] else "–"
            parent = r["epic_link_key"] or r["parent_key"] or "–"
            extra = f"<td>{parent}</td>" if extra_col else ""
            lbls = json.loads(r["labels"] or "[]")
            lbl_html = " ".join(f'<span class="lbl">{l}</span>' for l in lbls) if lbls else "–"
            out.append(
                f'<tr>'
                f'<td class="key"><a href="/ui/issue/{r["key"]}">{r["key"]}</a></td>'
                f'<td>{r["summary"]}</td>'
                f'<td>{_status_badge(r["status"])}</td>'
                f'<td>{pts}</td>'
                f'<td>{lbl_html}</td>'
                f'{extra}'
                f'</tr>'
            )
        return "".join(out)

    epic_head = "<tr><th>Key</th><th>Summary</th><th>Status</th><th>Points</th><th>Labels</th></tr>"
    story_head = "<tr><th>Key</th><th>Summary</th><th>Status</th><th>Points</th><th>Labels</th><th>Epic</th></tr>"

    html = f"""<!doctype html>
<html><head><title>Jira Simulator — {PROJECT_KEY}</title>{_CSS}</head>
<body>
<h1>Jira Simulator — project {PROJECT_KEY}</h1>
<div class="toolbar">
  <a href="/ui/create" class="btn btn-primary">+ Create Issue</a>
  <span class="meta" style="margin:0">
    <a href="/docs">Swagger API</a> &nbsp;|&nbsp;
    Data stored in <code>{DB_PATH}</code>
  </span>
</div>

<h2>Epics ({len(epics)})</h2>
<table>{epic_head}{rows(epics)}</table>

<h2>Stories ({len(stories)})</h2>
<table>{story_head}{rows(stories, extra_col='epic')}</table>
"""

    if others:
        html += f"<h2>Other ({len(others)})</h2><table>{epic_head}{rows(others)}</table>"

    html += "</body></html>"
    return HTMLResponse(html)

@app.get("/ui/issue/{key}", response_class=HTMLResponse)
def ui_issue(key: str):
    key = key.upper()
    with db() as conn:
        row = conn.execute("SELECT * FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        comments = conn.execute(
            "SELECT * FROM comments WHERE issue_key=? ORDER BY created_at", (key,)
        ).fetchall()
        out_links = conn.execute(
            "SELECT * FROM issue_links WHERE outward_key=?", (key,)
        ).fetchall()
        in_links = conn.execute(
            "SELECT * FROM issue_links WHERE inward_key=?", (key,)
        ).fetchall()
        children = conn.execute(
            "SELECT * FROM issues WHERE epic_link_key=? OR parent_key=? ORDER BY number",
            (key, key),
        ).fetchall()

    def field_row(label: str, value: Any) -> str:
        return f"<tr><td><b>{label}</b></td><td>{value or '–'}</td></tr>"

    pts = str(int(row["story_points"])) if row["story_points"] else "–"
    parent_link = (
        f'<a href="/ui/issue/{row["parent_key"]}">{row["parent_key"]}</a>'
        if row["parent_key"] else ""
    )
    epic_link = (
        f'<a href="/ui/issue/{row["epic_link_key"]}">{row["epic_link_key"]}</a>'
        if row["epic_link_key"] else ""
    )
    issue_labels = json.loads(row["labels"] or "[]")
    labels_html = " ".join(f'<span class="lbl">{l}</span>' for l in issue_labels) or "–"

    comments_html = "".join(
        f'<div class="comment"><div class="author">{c["author"]}</div>{c["body"]}</div>'
        for c in comments
    ) or "<p style='color:#888'>No comments.</p>"

    def link_rows(links, key_col: str) -> str:
        if not links:
            return "<p style='color:#888'>None.</p>"
        return "".join(
            f'<div><b>{lnk["type_name"]}</b> → '
            f'<a href="/ui/issue/{lnk[key_col]}">{lnk[key_col]}</a></div>'
            for lnk in links
        )

    children_html = ""
    if children:
        children_html = "<h2>Child issues</h2><table>"
        children_html += "<tr><th>Key</th><th>Summary</th><th>Status</th><th>Points</th></tr>"
        for c in children:
            pts_c = str(int(c["story_points"])) if c["story_points"] else "–"
            children_html += (
                f'<tr>'
                f'<td class="key"><a href="/ui/issue/{c["key"]}">{c["key"]}</a></td>'
                f'<td>{c["summary"]}</td>'
                f'<td>{_status_badge(c["status"])}</td>'
                f'<td>{pts_c}</td>'
                f'</tr>'
            )
        children_html += "</table>"

    html = f"""<!doctype html>
<html><head><title>{key} — Jira Simulator</title>{_CSS}</head>
<body>
<div class="back"><a href="/ui">← All issues</a></div>
<div class="toolbar">
  <h1 style="margin:0">{key}: {row["summary"]}</h1>
  <a href="/ui/issue/{key}/edit" class="btn btn-primary btn-sm">Edit</a>
</div>

<table style="width:auto;margin-bottom:1.5rem">
  {field_row("Type",        row["issuetype"])}
  {field_row("Status",      f'''
    <form class="inline-form" method="post" action="/ui/issue/{key}/transition">
      {_status_badge(row["status"])} &nbsp;→&nbsp;
      <select name="status">
        {"".join(f'<option value="{s}"{"selected" if s == row["status"] else ""}>{s}</option>' for s in STATUSES)}
      </select>
      <button type="submit" class="btn btn-primary btn-sm">Update</button>
    </form>''')}
  {field_row("Resolution",  row["resolution"])}
  {field_row("Story points",pts)}
  {field_row("Labels",      labels_html)}
  {field_row("Parent",      parent_link)}
  {field_row("Epic link",   epic_link)}
</table>

<h2>Description</h2>
<div style="white-space:pre-wrap;background:#f4f5f7;padding:1rem;border-radius:4px">
{row["description"] or "<em>No description.</em>"}
</div>

{children_html}

<h2>Links</h2>
<div class="section">
  <b>Outward:</b> {link_rows(out_links, "inward_key")}
  <b>Inward:</b>  {link_rows(in_links, "outward_key")}
</div>

<h2>Comments ({len(comments)})</h2>
{comments_html}

<form class="sim-form" method="post" action="/ui/issue/{key}/comment" style="margin-top:1rem">
  <label for="comment-body">Add a comment</label>
  <textarea name="body" id="comment-body" style="min-height:80px" placeholder="Write a comment..."></textarea>
  <div class="form-actions">
    <button type="submit" class="btn btn-green btn-sm">Add Comment</button>
  </div>
</form>
</body></html>
"""
    return HTMLResponse(html)

# ── UI: Create / Edit / Comment / Transition ────────────────────────────────

ISSUE_TYPES = ["Epic", "Story", "Task", "Bug"]
STATUSES = ["To Do", "In Progress", "Done", "Won't Do"]

def _issue_form_html(
    action: str,
    *,
    title: str,
    epics: list,
    issues: list,
    values: dict | None = None,
    show_type: bool = True,
) -> str:
    esc = _html.escape
    v = values or {}
    summary = esc(v.get("summary", ""))
    description = esc(v.get("description", ""))
    issuetype = v.get("issuetype", "Story")
    story_points = v.get("story_points", "")
    epic_link_key = v.get("epic_link_key", "")
    parent_key = v.get("parent_key", "")
    labels = esc(v.get("labels", ""))

    type_options = "".join(
        f'<option value="{t}" {"selected" if t == issuetype else ""}>{t}</option>'
        for t in ISSUE_TYPES
    )
    type_field = f"""
      <label for="issuetype">Issue Type</label>
      <select name="issuetype" id="issuetype">{type_options}</select>
    """ if show_type else f'<input type="hidden" name="issuetype" value="{issuetype}">'

    epic_options = '<option value="">— None —</option>' + "".join(
        f'<option value="{e["key"]}" {"selected" if e["key"] == epic_link_key else ""}>'
        f'{e["key"]} — {esc(e["summary"])}</option>'
        for e in epics
    )
    parent_options = '<option value="">— None —</option>' + "".join(
        f'<option value="{i["key"]}" {"selected" if i["key"] == parent_key else ""}>'
        f'{i["key"]} — {esc(i["summary"])}</option>'
        for i in issues
    )

    pts_val = f'value="{int(story_points)}"' if story_points else ""

    return f"""<!doctype html>
<html><head><title>{title} — Jira Simulator</title>{_CSS}</head>
<body>
<div class="back"><a href="/ui">← All issues</a></div>
<h1>{title}</h1>
<form class="sim-form" method="post" action="{action}">
  <label for="summary">Summary</label>
  <input type="text" name="summary" id="summary" value="{summary}" required>

  {type_field}

  <label for="description">Description</label>
  <textarea name="description" id="description">{description}</textarea>

  <label for="story_points">Story Points</label>
  <input type="number" name="story_points" id="story_points" min="0" step="1" {pts_val}>

  <label for="epic_link_key">Epic Link</label>
  <select name="epic_link_key" id="epic_link_key">{epic_options}</select>

  <label for="parent_key">Parent</label>
  <select name="parent_key" id="parent_key">{parent_options}</select>

  <label for="labels">Labels <span style="font-weight:normal;color:#888">(comma-separated)</span></label>
  <input type="text" name="labels" id="labels" value="{labels}">

  <div class="form-actions">
    <button type="submit" class="btn btn-primary">Save</button>
  </div>
</form>
</body></html>"""


@app.get("/ui/create", response_class=HTMLResponse)
def ui_create():
    with db() as conn:
        epics = conn.execute(
            "SELECT key, summary FROM issues WHERE issuetype='Epic' ORDER BY number"
        ).fetchall()
        all_issues = conn.execute(
            "SELECT key, summary FROM issues ORDER BY number"
        ).fetchall()
    return HTMLResponse(_issue_form_html(
        "/ui/create",
        title="Create Issue",
        epics=[dict(e) for e in epics],
        issues=[dict(i) for i in all_issues],
    ))


@app.post("/ui/create")
async def ui_create_submit(
    summary: str = Form(""),
    description: str = Form(""),
    issuetype: str = Form("Story"),
    story_points: str = Form(""),
    epic_link_key: str = Form(""),
    parent_key: str = Form(""),
    labels: str = Form(""),
):
    key = _next_key(PROJECT_KEY)
    number = int(key.split("-")[1])
    pts = float(story_points) if story_points.strip() else None
    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels.strip() else []
    with db() as conn:
        conn.execute(
            """INSERT INTO issues
               (key, project, number, summary, description, issuetype,
                status, story_points, epic_link_key, parent_key, labels, fix_versions, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                key, PROJECT_KEY, number,
                summary,
                description or None,
                issuetype.title(),
                "To Do",
                pts,
                epic_link_key or None,
                parent_key or None,
                json.dumps(label_list),
                "[]",
                time.time(),
            ),
        )
    return RedirectResponse(url=f"/ui/issue/{key}", status_code=303)


@app.get("/ui/issue/{key}/edit", response_class=HTMLResponse)
def ui_edit(key: str):
    key = key.upper()
    with db() as conn:
        row = conn.execute("SELECT * FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        epics = conn.execute(
            "SELECT key, summary FROM issues WHERE issuetype='Epic' ORDER BY number"
        ).fetchall()
        all_issues = conn.execute(
            "SELECT key, summary FROM issues WHERE key != ? ORDER BY number", (key,)
        ).fetchall()
    labels_str = ", ".join(json.loads(row["labels"] or "[]"))
    return HTMLResponse(_issue_form_html(
        f"/ui/issue/{key}/edit",
        title=f"Edit {key}",
        epics=[dict(e) for e in epics],
        issues=[dict(i) for i in all_issues],
        values={
            "summary": row["summary"],
            "description": row["description"] or "",
            "issuetype": row["issuetype"],
            "story_points": row["story_points"],
            "epic_link_key": row["epic_link_key"] or "",
            "parent_key": row["parent_key"] or "",
            "labels": labels_str,
        },
        show_type=False,
    ))


@app.post("/ui/issue/{key}/edit")
async def ui_edit_submit(
    key: str,
    summary: str = Form(""),
    description: str = Form(""),
    issuetype: str = Form("Story"),
    story_points: str = Form(""),
    epic_link_key: str = Form(""),
    parent_key: str = Form(""),
    labels: str = Form(""),
):
    key = key.upper()
    pts = float(story_points) if story_points.strip() else None
    label_list = [l.strip() for l in labels.split(",") if l.strip()] if labels.strip() else []
    with db() as conn:
        row = conn.execute("SELECT key FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        conn.execute(
            """UPDATE issues SET summary=?, description=?, story_points=?,
               epic_link_key=?, parent_key=?, labels=? WHERE key=?""",
            (
                summary,
                description or None,
                pts,
                epic_link_key or None,
                parent_key or None,
                json.dumps(label_list),
                key,
            ),
        )
    return RedirectResponse(url=f"/ui/issue/{key}", status_code=303)


@app.post("/ui/issue/{key}/comment")
async def ui_add_comment(key: str, body: str = Form("")):
    key = key.upper()
    if not body.strip():
        return RedirectResponse(url=f"/ui/issue/{key}", status_code=303)
    with db() as conn:
        row = conn.execute("SELECT key FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        conn.execute(
            "INSERT INTO comments(issue_key, body, author, created_at) VALUES(?,?,?,?)",
            (key, body, "Web UI", time.time()),
        )
    return RedirectResponse(url=f"/ui/issue/{key}", status_code=303)


@app.post("/ui/issue/{key}/transition")
async def ui_transition(key: str, status: str = Form("To Do")):
    key = key.upper()
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    resolution = None
    if status == "Done":
        resolution = "Done"
    elif status == "Won't Do":
        resolution = "Won't Do"
    with db() as conn:
        row = conn.execute("SELECT key FROM issues WHERE key=?", (key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        conn.execute(
            "UPDATE issues SET status=?, resolution=? WHERE key=?",
            (status, resolution, key),
        )
    return RedirectResponse(url=f"/ui/issue/{key}", status_code=303)


# ── Root redirect ─────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return RedirectResponse(url="/ui")
