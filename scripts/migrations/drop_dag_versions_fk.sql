-- 去掉 dag_versions.novel_id 外键约束（模板 @tmpl: 前缀不在 novels 表中）
PRAGMA foreign_keys = OFF;

CREATE TABLE dag_versions_tmp (
    id TEXT PRIMARY KEY,
    novel_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    dag_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    nodes_json TEXT NOT NULL,
    edges_json TEXT NOT NULL,
    fingerprint TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(novel_id, version)
);

INSERT INTO dag_versions_tmp SELECT * FROM dag_versions;
DROP TABLE dag_versions;
ALTER TABLE dag_versions_tmp RENAME TO dag_versions;

CREATE INDEX IF NOT EXISTS idx_dag_versions_novel ON dag_versions(novel_id);
CREATE INDEX IF NOT EXISTS idx_dag_versions_nv ON dag_versions(novel_id, version);

PRAGMA foreign_keys = ON;
