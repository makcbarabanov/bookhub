-- BookHub v0.3.2 — Кастинг: структурированные персонажи per book

CREATE TABLE IF NOT EXISTS book_characters (
    id             BIGSERIAL PRIMARY KEY,
    book_id        BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    name           VARCHAR(120) NOT NULL,
    role_type      VARCHAR(20) NOT NULL DEFAULT 'secondary'
                   CHECK (role_type IN ('protagonist', 'antagonist', 'secondary')),
    summary        VARCHAR(300) NOT NULL,
    bio            TEXT DEFAULT '',
    relations_json JSONB DEFAULT '{}'::jsonb,
    first_ch_id    VARCHAR(10) NULL,
    color          VARCHAR(7) DEFAULT '#888888',
    avatar_url     VARCHAR(255) NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(book_id, name)
);

CREATE INDEX IF NOT EXISTS idx_book_characters_book ON book_characters (book_id);
