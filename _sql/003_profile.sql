-- BookHub v0.3 — профиль автора (ФИО)

ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(80);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR(80);
ALTER TABLE users ADD COLUMN IF NOT EXISTS patronymic VARCHAR(80);

UPDATE users
SET first_name = display_name
WHERE first_name IS NULL AND display_name IS NOT NULL AND display_name <> '';
