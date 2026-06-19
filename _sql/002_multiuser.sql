-- BookHub v0.2 — мультиавтор (additive + drop revisions)

DROP TABLE IF EXISTS revisions;

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    phone_e164 VARCHAR(16) NOT NULL UNIQUE,
    login VARCHAR(64) UNIQUE,
    password_hash TEXT NOT NULL,
    display_name VARCHAR(120),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_login ON users (login);

ALTER TABLE books ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id);
ALTER TABLE books ADD COLUMN IF NOT EXISTS slug VARCHAR(64);
ALTER TABLE books ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE books ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_books_owner ON books (owner_user_id);

CREATE TABLE IF NOT EXISTS book_memberships (
    id BIGSERIAL PRIMARY KEY,
    book_id BIGINT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL DEFAULT 'owner'
        CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (book_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_memberships_user ON book_memberships (user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_book ON book_memberships (book_id);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    active_book_id BIGINT REFERENCES books(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
