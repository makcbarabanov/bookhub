-- Заметки: порядок и секции (чек-лист → заметки)

ALTER TABLE book_notes
    ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;

ALTER TABLE book_notes
    ADD COLUMN IF NOT EXISTS is_section BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_book_notes_book_sort
    ON book_notes (book_id, sort_order, id);
