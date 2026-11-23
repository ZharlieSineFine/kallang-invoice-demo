-- 003_export_history: an exported invoice can be sent to SAP again (user's request, 2026-11-20).
-- export_rows keeps one row per (batch, invoice), so every send stays in the history. The
-- UNIQUE on doc_id, which allowed one export per invoice, goes; the primary key
-- (batch_id, doc_id) still stops an invoice appearing twice in one batch. The index keeps
-- "which batches sent this invoice" fast without the unique constraint's own index.
-- Running it again changes nothing.

ALTER TABLE export_rows DROP CONSTRAINT IF EXISTS export_rows_doc_id_key;
CREATE INDEX IF NOT EXISTS export_rows_doc_id_idx ON export_rows (doc_id);
