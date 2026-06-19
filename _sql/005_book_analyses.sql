-- BookHub v0.4 — кэш «Советы ИИ» и учёт токенов

CREATE TABLE IF NOT EXISTS book_analyses (
    book_id BIGINT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    analysis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    model VARCHAR(128),
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_usage_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id BIGINT REFERENCES books(id) ON DELETE SET NULL,
    endpoint VARCHAR(64) NOT NULL,
    model VARCHAR(128),
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_user_time ON ai_usage_log (user_id, created_at DESC);
