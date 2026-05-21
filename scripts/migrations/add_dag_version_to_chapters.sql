-- 为 chapters 表添加 DAG 版本追踪列（幂等）
ALTER TABLE chapters ADD COLUMN dag_version_id TEXT;
ALTER TABLE chapters ADD COLUMN dag_fingerprint TEXT;
