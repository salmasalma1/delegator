# Checkpoint store compatibility report

Feature: integrate checkpoint store into the delegator.

Documentation only. Nothing under a `persistence/basant/` tree was modified (that tree is not in this workspace). Team 2 schema, `AgentState`, and Vision coordinate convention were not changed.

## Sources actually read

Requested paths vs what exists:

| Requested | Status | Used instead |
|---|---|---|
| `persistence/basant/schema` | **missing** | `checkpointSaver/schema.sql` |
| `persistence/basant/db_helpers.py` | **missing** | `checkpointSaver/db_helpers.py` |
| `persistence/basant/sqlite_saver.py` | **missing** | `checkpointSaver/sqlite_saver.py` |
| `persistence/basant/check_db.py` | **missing** | `checkpointSaver/check_db.py` |
| `persistence/basant/test_saver.py` | **missing** | `checkpointSaver/test_saver.py` and `checkpointSaver/tests/test_checkpoint.py` |
| `persistence/schema.sql` | **missing** | none in repo |
| `persistence/db_shim.py` | **missing** | none in repo |
| `persistence/audit.py` | **missing** | none in repo |
| `graph/nodes/verify.py` | **missing** (filename mismatch) | `graph/nodes/verifiy.py` (typo); `graph/builder.py` and `graph/nodes/__init__.py` import `graph.nodes.verify` |
| `graph/builder.py` | present | `graph/builder.py` |
| `uploads/checkpoints.txt` | **missing** | `C:\Users\T\Documents\checkpoints.txt` (only file on this machine whose body is the 3-table checkpoint spec) |

**AMBIGUOUS: Is `checkpointSaver/` the intended `persistence/basant/` drop, or is Basant's tree still unpublished?** — needs a decision. This report treats `checkpointSaver/` as "her code".

**AMBIGUOUS: Are `persistence/schema.sql`, `persistence/db_shim.py`, and `persistence/audit.py` Team-2 / orchestrator artifacts that have not been copied into this repo?** — needs a decision. They cannot be compared column-by-column until they exist.

Spec baseline for sections A–B is `C:\Users\T\Documents\checkpoints.txt`. Team 2 coordinate evidence for section C is `graph/subgraphs/app_supgraph.py` plus `C:\Users\T\Documents\Desktop Adapter.txt`.

Live SQLite files inspected (read-only) on 2026-10-24:

- `checkpointSaver/agent.db` — domain tables; 6 rows in `checkpoints`; 0 rows in `steps`; 0 rows in `audit_log`.
- `checkpointSaver/langgraph_checkpoints.db` — LangGraph tables; 6 rows in `checkpoints`; 6 rows in `writes`.

---

## A. TABLE MATRIX

Spec source: `C:\Users\T\Documents\checkpoints.txt` lines 10–36. Her DDL: `checkpointSaver/schema.sql`. Live DDL: `PRAGMA table_info` on `checkpointSaver/agent.db`.

### A.1 Table `checkpoints`

Table exists in her DDL? **YES** (`checkpointSaver/schema.sql` lines 2–8). Exists in `agent.db`? **YES**.

| Spec column | Spec type / note | Her `schema.sql` | Live `agent.db` | Missing / extra | Column verdict |
|---|---|---|---|---|---|
| `checkpoint_id` | `TEXT PRIMARY KEY` | `checkpoint_id TEXT PRIMARY KEY` (L3) | `checkpoint_id TEXT`, pk=1 | neither | MATCH |
| `session_id` | `TEXT` | `session_id TEXT` (L4) | `session_id TEXT` | neither | MATCH |
| `task_id` | `TEXT` | `task_id TEXT` (L5) | `task_id TEXT` | neither | MATCH |
| `step_number` | `INTEGER` | `step_number INTEGER` (L6) | `step_number INTEGER` | neither | MATCH |
| `agent_state_json` | `TEXT` (full AgentState as JSON) | `agent_state_json TEXT` (L7) | `agent_state_json TEXT` | neither | MATCH |
| `created_at` | `TEXT` (ISO8601) | `created_at TEXT` (L8); no ISO constraint in SQL | `created_at TEXT`; sample value `2026-10-23T14:50:30.824688+00:00` written by `datetime.now(timezone.utc).isoformat()` in `db_helpers.py` L43 | neither | MATCH (format by writer, not by DDL) |

Extra columns in her table vs spec: **none**.

Missing columns vs spec: **none**.

DDL verdict: **COMPATIBLE**.

Semantic notes (not extra columns):

- Spec says `agent_state_json` is full `AgentState`. Her writer dumps the dict it was given (`db_helpers.py` L68). Sample rows only contain `{session_id, task_id, step_number, status}` — test fixtures, not `graph/state.py` `AgentState`.
- `graph/state.py` has `current_step` (L7), not `step_number`. Her saver reads `state.get("step_number", 0)` (`db_helpers.py` L47). Wiring `AgentState` as-is stores `step_number=0` even when `current_step` is set. That is a field-name mismatch, not a SQL column mismatch.

### A.2 Table `steps`

Table exists in her DDL? **YES** (`checkpointSaver/schema.sql` lines 11–23). Exists in `agent.db`? **YES**. Row count: **0**.

| Spec column | Spec type / note | Her `schema.sql` | Live `agent.db` | Missing / extra | Column verdict |
|---|---|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `id INTEGER PRIMARY KEY AUTOINCREMENT` (L12) | `id INTEGER`, pk=1 | neither | MATCH |
| `checkpoint_id` | `TEXT` (FK) | `checkpoint_id TEXT` + `FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id)` (L13, L21–22) | `checkpoint_id TEXT`; FK present in `sqlite_master` SQL | neither | MATCH |
| `step_id` | `INTEGER` | `step_id INTEGER` (L14) | `step_id INTEGER` | neither | MATCH |
| `description` | `TEXT` | `description TEXT` (L15) | `description TEXT` | neither | MATCH |
| `app` | `TEXT` (Chrome/Notepad/Explorer/System) | `app TEXT` (L16); **no CHECK** for the four apps | `app TEXT` | neither | MATCH type; allowed values **not enforced** |
| `status` | `TEXT` (pending/done/failed) | `status TEXT` (L17); **no CHECK** | `status TEXT` | neither | MATCH type; allowed values **not enforced** |
| `bbox_norm` | `TEXT` (JSON `[x1,y1,x2,y2]` or null) | `bbox_norm TEXT` (L18); **no JSON / shape CHECK** | `bbox_norm TEXT` | neither | MATCH type; shape **not enforced** (see C) |
| `confidence` | `REAL` | `confidence REAL` (L19) | `confidence REAL` | neither | MATCH |
| `source` | `TEXT` | `source TEXT` (L20) | `source TEXT` | neither | MATCH |

Extra columns vs spec: **none**.

Missing columns vs spec: **none**.

Writer: `save_checkpoint` inserts **only** into `checkpoints` (`db_helpers.py` L51–71). There is **no** `INSERT INTO steps` anywhere under `checkpointSaver/`.

DDL verdict: **COMPATIBLE**. Runtime population: **NEEDS ADAPTER**.

### A.3 Table `audit_log`

Table exists in her DDL? **YES** (`checkpointSaver/schema.sql` lines 25–33). Exists in `agent.db`? **YES**. Row count: **0**.

| Spec column | Spec type / note | Her `schema.sql` | Live `agent.db` | Missing / extra | Column verdict |
|---|---|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `id INTEGER PRIMARY KEY AUTOINCREMENT` (L26) | `id INTEGER`, pk=1 | neither | MATCH |
| `checkpoint_id` | `TEXT` (FK) | `checkpoint_id TEXT` + FK to `checkpoints(checkpoint_id)` (L27, L31–32) | `checkpoint_id TEXT`; FK in CREATE SQL | neither | MATCH |
| `safety_decision` | `TEXT` (allow/ask/refuse) | `safety_decision TEXT` (L28); **no CHECK** | `safety_decision TEXT` | neither | MATCH type; allowed values **not enforced** |
| `latency_ms` | `INTEGER` | `latency_ms INTEGER` (L29) | `latency_ms INTEGER` | neither | MATCH |
| `created_at` | `TEXT` | `created_at TEXT` (L30) | `created_at TEXT` | neither | MATCH |

Extra columns vs spec: **none**.

Missing columns vs spec: **none**.

Writer: no `INSERT INTO audit_log` under `checkpointSaver/`. `persistence/audit.py` is missing, so her code cannot be compared to that module.

Safety vocabulary elsewhere: `C:\Users\T\Documents\saftey.txt` L9 uses `"allow" | "ask" | "deny"`. Spec `checkpoints.txt` L34 uses `allow/ask/refuse`. Subgraph mock uses `"approved"` (`graph/subgraphs/app_supgraph.py` L49). Those are value-set conflicts, not extra SQL columns.

**AMBIGUOUS: Is audit vocabulary `refuse`, `deny`, or `approved`?** — needs a decision. Do not change Team 2 or her schema in this step.

DDL verdict: **COMPATIBLE**. Runtime population: **NEEDS ADAPTER**. Value-set vs Safety spec: **CONFLICT** (documented, not a column mismatch).

### A.4 Same name, different schema (`checkpoints`)

LangGraph's `checkpoints` table **also exists**, in a **different file** today. Full comparison is section D. If both DDLs are applied to one file, SQLite `CREATE TABLE IF NOT EXISTS checkpoints` will **keep whichever table was created first** and the other writer will fail at runtime.

---

## B. API MATRIX

Spec source: `C:\Users\T\Documents\checkpoints.txt` lines 39–45. Implementation: `checkpointSaver/db_helpers.py`.

| Spec API | Present? | Exact signature in her code | Return type in her code | Deviation | Verdict |
|---|---|---|---|---|---|
| `init_db(path="agent.db")` → creates tables if not exists | YES, L13–28 | `def init_db(path="agent.db"):` | `str` (absolute path, L28) | Spec does not name a return type. Relative `path` is resolved against `checkpointSaver/` (`L17–18`), not CWD. Always `PRAGMA foreign_keys = ON` then `executescript(schema.sql)`. | **COMPATIBLE** (return value is extra, not contradictory) |
| `save_checkpoint(state: AgentState) -> checkpoint_id` | YES, L37–73 | `def save_checkpoint(state: dict) -> str:` | `str` (UUID from `uuid.uuid4()`, L42, L73) | Annotated `dict`, not `AgentState`. Raises `TypeError` if not a dict (L39–40). Does **not** insert `steps` or `audit_log`. Reads `step_number`, not `current_step`. Always opens `init_db()` with **no path argument** (L49), so a custom `init_db("other.db")` is ignored by save/load/list. | **NEEDS ADAPTER** |
| `load_checkpoint(checkpoint_id: str) -> AgentState` | YES, L76–91 | `def load_checkpoint(checkpoint_id: str) -> dict:` | `dict` via `json.loads` | Return annotated `dict`, not `AgentState`. Missing id raises `ValueError` (L88–89); spec is silent on miss. Uses default `agent.db` only. | **COMPATIBLE** if callers treat `TypedDict` as `dict`; miss-behavior unspecified by spec |
| `get_last_checkpoint(session_id: str) -> AgentState \| None` | YES, L94–111 | `def get_last_checkpoint(session_id: str) -> Optional[dict]:` | `Optional[dict]` | Annotated `dict` not `AgentState`. "Latest" = `ORDER BY created_at DESC LIMIT 1` (L102–103). Equal timestamps: **AMBIGUOUS** (no tie-breaker). | **COMPATIBLE** with the same TypedDict caveat |
| `list_checkpoints(session_id: str) -> list[checkpoint_id]` | YES, L116–129 | `def list_checkpoints(session_id: str) -> list[str]:` | `list[str]` of `checkpoint_id`, `ORDER BY created_at ASC` | Matches spec. Default db only. | **COMPATIBLE** |

Extra APIs (not in spec):

| API | File | Signature | Note |
|---|---|---|---|
| `get_checkpointer(db_path="langgraph_checkpoints.db")` | `checkpointSaver/sqlite_saver.py` L6–10 | context manager yielding LangGraph `SqliteSaver` | Not the domain helper API. Default **filename differs** from `init_db`'s `agent.db`. |

Tests present:

- `checkpointSaver/tests/test_checkpoint.py` — `test_save_and_load_checkpoint`, `test_get_last_checkpoint`, `test_missing_session_returns_none` (3 tests, matches spec deliverable #5).
- `checkpointSaver/check_db.py` — smoke for `list_checkpoints`.
- `checkpointSaver/test_saver.py` — LangGraph `SqliteSaver` round-trip, not the domain API.

Delegator wiring:

- `graph/builder.py` L34 uses `MemorySaver()`, not `get_checkpointer` and not `save_checkpoint`.
- `graph/nodes/verifiy.py` L3–5 sets `saved_checkpoint_id` to a **fresh** `uuid4()` and does **not** call `save_checkpoint`.

---

## C. COORDINATE FORMAT

### C.1 What `steps.bbox_norm` holds in her code

Her SQL: `bbox_norm TEXT` (`checkpointSaver/schema.sql` L18). No CHECK, no JSON parse, no comment that the TEXT is `[x1,y1,x2,y2]`.

Her Python: **does not write this column**. `save_checkpoint` never inserts into `steps`. Live `agent.db` `steps` count is **0**. Therefore her code currently holds **no runtime shape** for `steps.bbox_norm`.

The spec's intended shape is only in `C:\Users\T\Documents\checkpoints.txt` L27:

```
bbox_norm TEXT (JSON [x1,y1,x2,y2] or null)
```

That comment is **not** copied into `schema.sql`.

### C.2 Spec vs Team 2 emit

Spec: `[x1,y1,x2,y2]` — `C:\Users\T\Documents\checkpoints.txt` L27.

Team 2 / Vision emit in **this** repo (`graph/subgraphs/app_supgraph.py` L28–32):

```python
def fallback_perceive(app: str, target: str = "button"):
    ...
            {"element_id": f"el_{uuid.uuid4().hex[:4]}", "bbox_norm": [0.31, 0.45, 0.08, 0.04], "label": "button", "text": target, "conf": 0.82, "source": "fallback"}
```

That literal is **not** a valid corner-corner box: if it were `[x1,y1,x2,y2]`, then `x2=0.08 < x1=0.31` and `y2=0.04 < y1=0.45`.

The same four numbers appear as Team 2's documented click contract (`C:\Users\T\Documents\Desktop Adapter.txt` L12 and L47):

```
- click(bbox_norm: [x, y, w, h] in [0,1]) -> bool
...
- python -m execution --action click --bbox "[0.31,0.45,0.08,0.04]"
```

So Team 2 documents **width/height**, not opposite-corner.

**AMBIGUOUS: are the first two numbers top-left `(x, y)` or center `(cx, cy)`?** Adapter text says `[x, y, w, h]` (`Desktop Adapter.txt` L12). This report does **not** treat that as proven `[cx,cy,w,h]`. It **does** prove the emit is **not** spec `[x1,y1,x2,y2]`.

Real Vision path: `perceive_screen` calls `nelly_vision.perception.perceive` when import succeeds (`app_supgraph.py` L21–22, L40–42). `nelly_vision` is not in this workspace, so the **real** detector's box convention is **AMBIGUOUS** — needs a decision / that file.

### C.3 Coordinate verdict

**CONFLICT** between checkpoint spec `[x1,y1,x2,y2]` and Team 2 documented/emitted `[x, y, w, h]` (same numbers as fallback). Hard rule: do not change Team 2's convention. Adapter must convert if `steps.bbox_norm` is to store spec JSON.

---

## D. CHECKPOINTER

### D.1 Does `sqlite_saver.py` use LangGraph's `SqliteSaver`?

**YES.** Quote:

```2:10:checkpointSaver/sqlite_saver.py
from contextlib import contextmanager
from langgraph.checkpoint.sqlite import SqliteSaver


@contextmanager
def get_checkpointer(db_path="langgraph_checkpoints.db"):
    """Provide a LangGraph SQLite checkpointer."""
    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        yield checkpointer
```

`checkpointSaver/test_saver.py` L4 imports `get_checkpointer`, L22–23 compiles a graph with that checkpointer, L27 uses `thread_id`.

This environment's `langgraph==0.2.39` has **no** `langgraph.checkpoint.sqlite` module (import failed 2026-10-24). The on-disk `langgraph_checkpoints.db` nevertheless contains LangGraph tables and `thread_id='test_thread_001'` rows, so `SqliteSaver` **did** run in some environment. **AMBIGUOUS: which package version created that file?** — needs a decision if CI must reproduce it.

### D.2 Does it create LangGraph's `checkpoints` table (`thread_id`, …) in the **same file** as the domain tables?

**Not in the current defaults.** Two files:

| File | Who creates it | `checkpoints` schema |
|---|---|---|
| `checkpointSaver/agent.db` | `init_db` → `schema.sql` | domain: `checkpoint_id, session_id, task_id, step_number, agent_state_json, created_at` |
| `checkpointSaver/langgraph_checkpoints.db` | `SqliteSaver.from_conn_string` | LangGraph, live SQL: |

```sql
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint BLOB,
    metadata BLOB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
)
```

Companion LangGraph table in **that same file**: `writes` (`thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value`).

Same table name, different columns: **YES**. Same file today: **NO**.

### D.3 Where same-file collision **is** implied

`graph/builder.py` L34:

```34:35:graph/builder.py
    checkpointer = MemorySaver()  # -> SqliteSaver.from_conn_string("agent.db")
    graph = builder.compile(checkpointer=checkpointer)
```

If that comment is followed, LangGraph `SqliteSaver` opens **`agent.db`**, which already has domain `CREATE TABLE IF NOT EXISTS checkpoints (...)`. `IF NOT EXISTS` will **not** replace her table. LangGraph then `INSERT`s `thread_id` / BLOBs into a table whose columns are `session_id, task_id, step_number, ...` → **runtime crash**. Conversely, if LangGraph created the file first, `init_db` would skip creating the domain `checkpoints` table and `save_checkpoint`'s INSERT would crash.

That is the "same table name + different schema = runtime crash" case. It is **latent** in the builder comment, **not** how `get_checkpointer`'s default path behaves.

### D.4 Checkpointer verdict

Current two-file layout: **NEEDS ADAPTER** (wire `get_checkpointer` into `build_graph`; keep files separate **or** rename one table). Following the `builder.py` comment onto `agent.db`: **CONFLICT**.

---

## E. FILE LAYOUT

### E.1 Files her code creates / expects

| Path | Role | Created by | Expected by |
|---|---|---|---|
| `checkpointSaver/agent.db` | domain `checkpoints` / `steps` / `audit_log` | `init_db(path="agent.db")` resolves to `checkpointSaver/agent.db` (`db_helpers.py` L13–18). File exists, 24576 bytes, 6 domain checkpoint rows. | `save_checkpoint`, `load_checkpoint`, `get_last_checkpoint`, `list_checkpoints` (all call `init_db()` with no args) |
| `checkpointSaver/langgraph_checkpoints.db` | LangGraph `checkpoints` + `writes` | `get_checkpointer()` default (`sqlite_saver.py` L7). File exists, 20480 bytes, 6 LangGraph checkpoint rows, `type='msgpack'`. | `test_saver.py` L22 |
| `checkpointSaver/schema.sql` | domain DDL | source file, not a db | `init_db` L11, L25–26 |
| CWD `agent.db` | — | **not** created by current helpers (relative path is joined to `checkpointSaver/`) | `builder.py` comment `SqliteSaver.from_conn_string("agent.db")` would create/open **process CWD** `agent.db`, a **third** location |
| CWD `langgraph_checkpoints.db` | — | `from_conn_string(db_path)` uses the string as given (`sqlite_saver.py` L9), **not** resolved against `BASE_DIR` | if tests are run from `checkpointSaver/`, file lands there; if run from repo root, it would land in CWD. Existing file is under `checkpointSaver/`. **AMBIGUOUS** which cwd produced it. |

`graph/builder.py` currently uses in-memory `MemorySaver()` — the running delegator **does not** create either `.db` file.

### E.2 WAL / SHM side files

Observed 2026-10-24 listing of `checkpointSaver/`:

- `agent.db-wal` — **absent**
- `agent.db-shm` — **absent**
- `langgraph_checkpoints.db-wal` — **absent**
- `langgraph_checkpoints.db-shm` — **absent**

The 2026-10-24 `before spec-kit` commit **did** include `checkpointSaver/langgraph_checkpoints.db-shm` and `checkpointSaver/langgraph_checkpoints.db-wal`. Those are SQLite WAL sidecar files. They appear while a WAL-mode connection is open (typical for LangGraph `SqliteSaver`) and can disappear after checkpoint. They must not be treated as schema. They should not be committed.

`checkpointSaver/.gitignore` ignores `.venv/`, `venv/`, `__pycache__/`, `.env`, `.DS_Store` only — **not** `*.db`, `*-wal`, or `*-shm`.

---

## F. VERDICT PER AREA

| Area | Verdict | Why |
|---|---|---|
| Domain table DDL (`checkpoints`, `steps`, `audit_log`) vs `checkpoints.txt` | **COMPATIBLE** | Column names and types match spec one-for-one; no extras, no missing columns. |
| Domain writers (`steps`, `audit_log` rows) | **NEEDS ADAPTER** | Tables exist; `save_checkpoint` never fills them; live counts are 0. |
| Domain helper API | **NEEDS ADAPTER** | Five names exist; `dict` vs `AgentState`; `step_number` vs `current_step`; save/load ignore custom db path; save does not persist steps/audit. |
| `init_db` / `load` / `get_last` / `list` signatures | **COMPATIBLE** with TypedDict-as-dict | See matrix B. |
| Coordinate `bbox_norm` | **CONFLICT** | Spec `[x1,y1,x2,y2]`; Team 2 fallback + adapter `[x, y, w, h]` with proven non-corner numbers at `app_supgraph.py` L32. Her column is unenforced TEXT and unused. |
| LangGraph checkpointer vs domain `checkpoints` table | **CONFLICT** if same file; **NEEDS ADAPTER** at current two-file + `MemorySaver` wiring | Same name, different schema (D). Crash if `SqliteSaver` is pointed at `agent.db` as `builder.py` L34 comments. |
| File layout | **NEEDS ADAPTER** | Two `.db` files plus a third path implied by the builder comment; WAL/SHM sidecars; `.gitignore` does not exclude them. |
| `persistence/schema.sql`, `db_shim.py`, `audit.py` | **AMBIGUOUS** | Files not in repo — cannot score COMPATIBLE vs CONFLICT. |
| `graph/nodes/verify.py` vs `verifiy.py` | **NEEDS ADAPTER** | Verify node does not call her saver; import path `verify` vs filename `verifiy.py`. |

### Integration implication (documentation only)

Keep domain tables and LangGraph tables in **different files** (or rename one `checkpoints` table). Do not follow `SqliteSaver.from_conn_string("agent.db")` while `schema.sql` also defines `checkpoints`. Convert Vision/Team 2 boxes before storing spec `[x1,y1,x2,y2]`; do not change Team 2 emit. Call `save_checkpoint` from verify (or a shim) instead of minting an unused UUID. Fill `steps` / `audit_log` only after those decisions.

### Open decisions

1. **AMBIGUOUS: Map `checkpointSaver/` → `persistence/basant/` or wait for Basant's tree?** — needs a decision.
2. **AMBIGUOUS: Where are `persistence/schema.sql`, `db_shim.py`, `audit.py`?** — needs a decision.
3. **AMBIGUOUS: `bbox_norm` first two numbers = top-left or center?** — needs a decision. Proven: not `[x1,y1,x2,y2]`.
4. **AMBIGUOUS: Safety enum `refuse` vs `deny` vs subgraph `approved`?** — needs a decision.
5. **AMBIGUOUS: One SQLite file or two?** — needs a decision. Same-file `checkpoints` is a crash.
6. **AMBIGUOUS: `step_number` (her saver) vs `current_step` (`AgentState`)?** — needs a decision. Do not change `AgentState` in this step.
)
