-- BookHub v0.3 — служебные вкладки per book

CREATE TABLE IF NOT EXISTS book_service (
    book_id BIGINT PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    checklist_html TEXT NOT NULL DEFAULT '',
    heroes_text TEXT NOT NULL DEFAULT '',
    plot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    checklist_updated_at TIMESTAMPTZ,
    heroes_updated_at TIMESTAMPTZ,
    plot_updated_at TIMESTAMPTZ
);
