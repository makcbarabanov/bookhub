-- BookHub v0.3 — Морфеус: чат, заметки, ai_summary

ALTER TABLE books ADD COLUMN IF NOT EXISTS ai_summary TEXT DEFAULT '';

CREATE TABLE IF NOT EXISTS book_notes (
    id          BIGSERIAL PRIMARY KEY,
    book_id     BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    title       VARCHAR(255) NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_book_notes_book ON book_notes (book_id);

CREATE TABLE IF NOT EXISTS book_chat_messages (
    id          BIGSERIAL PRIMARY KEY,
    book_id     BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    sender      VARCHAR(10) NOT NULL CHECK (sender IN ('user', 'ai')),
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_book_chat_book ON book_chat_messages (book_id);
CREATE INDEX IF NOT EXISTS idx_book_chat_book_time ON book_chat_messages (book_id, created_at DESC);
