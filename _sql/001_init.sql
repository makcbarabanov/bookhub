-- BookHub v0.1 — additive schema
CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chapters (
    id SERIAL PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    ch_id VARCHAR(32) NOT NULL,
    title VARCHAR(512) NOT NULL,
    act_number SMALLINT NOT NULL DEFAULT 1,
    emoji VARCHAR(8) NOT NULL DEFAULT '🟢',
    content TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (book_id, ch_id)
);

CREATE INDEX IF NOT EXISTS idx_chapters_book_sort ON chapters (book_id, sort_order);

CREATE TABLE IF NOT EXISTS revisions (
    id SERIAL PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_revisions_chapter ON revisions (chapter_id, created_at DESC);
