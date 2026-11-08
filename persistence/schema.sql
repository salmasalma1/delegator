-- Checkpoint store schema, as agreed. Column names and types are frozen.
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id     TEXT PRIMARY KEY,
    session_id        TEXT,
    task_id           TEXT,
    step_number       INTEGER,
    agent_state_json  TEXT,
    created_at        TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id TEXT,
    step_id       INTEGER,
    description   TEXT,
    app           TEXT,
    status        TEXT,
    bbox_norm     TEXT,
    confidence    REAL,
    source        TEXT,
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    checkpoint_id   TEXT,
    safety_decision TEXT,
    latency_ms      INTEGER,
    created_at      TEXT,
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_steps_checkpoint     ON steps(checkpoint_id);