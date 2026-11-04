-- 001_init: Phase 0 schema for the ap database (contracts-v1).
-- Enum CHECK lists must match src/invoiceflow/contracts/enums.py (tested).
-- Rows in fields, line_items, and coding_lines are never updated in place:
-- a new version is inserted and the previous one gets is_current = false.

-- The runner creates this table before applying anything, so it can record versions.
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     text PRIMARY KEY,
  applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------ master data
-- Coding data is hypothetical (build plan section 5.5).
CREATE TABLE gl_accounts (
  code    text PRIMARY KEY,
  name    text NOT NULL,
  active  boolean NOT NULL DEFAULT true
);

CREATE TABLE cost_centers (
  code    text PRIMARY KEY,
  name    text NOT NULL,
  active  boolean NOT NULL DEFAULT true
);

CREATE TABLE tax_codes (
  code          text PRIMARY KEY,
  rate_percent  numeric(5,2) NOT NULL,
  description   text NOT NULL
);

CREATE TABLE venue_cost_centers (
  alias        text PRIMARY KEY,
  cost_center  text NOT NULL REFERENCES cost_centers (code)
);

CREATE TABLE vendors (
  vendor_id            text PRIMARY KEY,
  sap_vendor_no        text NOT NULL UNIQUE,
  name                 text NOT NULL,
  uen                  text,
  gst_reg_no           text,
  address              text,
  bank_name            text,
  bank_account         text,
  currency             char(3) NOT NULL DEFAULT 'SGD',
  locale               text NOT NULL DEFAULT 'SG',
  is_overseas          boolean NOT NULL DEFAULT false,
  default_gl           text REFERENCES gl_accounts (code),
  default_cost_center  text REFERENCES cost_centers (code),
  default_tax_code     text REFERENCES tax_codes (code),
  active               boolean NOT NULL DEFAULT true
);
CREATE INDEX vendors_gst_reg_no_idx ON vendors (gst_reg_no);

CREATE TABLE purchase_orders (
  po_number    text PRIMARY KEY,
  vendor_id    text NOT NULL REFERENCES vendors (vendor_id),
  currency     char(3) NOT NULL DEFAULT 'SGD',
  amount       numeric(14,2) NOT NULL,
  open_amount  numeric(14,2) NOT NULL,
  gl_account   text REFERENCES gl_accounts (code),
  cost_center  text REFERENCES cost_centers (code)
);

-- ----------------------------------------------------------------- bronze
CREATE TABLE bronze_files (
  file_id        uuid PRIMARY KEY,
  sha256         char(64) NOT NULL UNIQUE,
  original_name  text NOT NULL,
  source         text NOT NULL,
  sender         text,
  received_at    timestamptz NOT NULL,
  size_bytes     bigint NOT NULL CHECK (size_bytes >= 0),
  mime_type      text,
  path           text NOT NULL
);

-- ----------------------------------------------------------------- silver
CREATE TABLE documents (
  doc_id         uuid PRIMARY KEY,
  file_id        uuid NOT NULL REFERENCES bronze_files (file_id),
  doc_type       text,
  status         text NOT NULL,
  status_reason  text,
  vendor_id      text REFERENCES vendors (vendor_id),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_documents_status CHECK (status IN ('RECEIVED', 'PARSED', 'EXTRACTED',
    'AUTO_PASSED', 'NEEDS_REVIEW', 'ON_HOLD', 'MANUAL_ENTRY', 'NOT_INVOICE', 'APPROVED',
    'REJECTED', 'EXPORTED')),
  CONSTRAINT ck_documents_doc_type CHECK (doc_type IN ('TAX_INVOICE', 'SIMPLIFIED_TAX_INVOICE',
    'INVOICE', 'CREDIT_NOTE', 'DEBIT_NOTE', 'STATEMENT', 'QUOTATION', 'DELIVERY_ORDER', 'OTHER'))
);
CREATE INDEX documents_status_idx ON documents (status);

CREATE TABLE pages (
  doc_id         uuid NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
  page_no        int NOT NULL CHECK (page_no >= 1),
  text_source    text NOT NULL,
  width_pt       numeric NOT NULL,
  height_pt      numeric NOT NULL,
  image_path     text,
  words_path     text,
  ocr_mean_conf  numeric,
  PRIMARY KEY (doc_id, page_no),
  CONSTRAINT ck_pages_text_source CHECK (text_source IN ('PDF_TEXT', 'OCR', 'EINVOICE'))
);

CREATE TABLE extractions (
  extraction_id      uuid PRIMARY KEY,
  doc_id             uuid NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
  model              text NOT NULL,
  model_digest       text,
  prompt_version     text NOT NULL,
  schema_version     text NOT NULL,
  params             jsonb NOT NULL DEFAULT '{}'::jsonb,
  mode               text NOT NULL,
  raw_output         text NOT NULL,
  parsed             jsonb,
  valid              boolean NOT NULL,
  error              text,
  prompt_tokens      int,
  completion_tokens  int,
  latency_ms         int,
  created_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_extractions_mode CHECK (mode IN ('LIVE', 'REPLAY'))
);

CREATE TABLE fields (
  row_id         bigserial PRIMARY KEY,
  doc_id         uuid NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
  extraction_id  uuid REFERENCES extractions (extraction_id),
  name           text NOT NULL,
  value_raw      text,
  value_norm     text,
  page_no        int,
  x0 numeric, y0 numeric, x1 numeric, y1 numeric,   -- page fractions, 0-1
  match_type     text NOT NULL DEFAULT 'NONE',
  match_score    numeric NOT NULL DEFAULT 0,
  confidence     text NOT NULL,
  source         text NOT NULL,
  is_current     boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_fields_match_type CHECK (match_type IN ('EXACT', 'NUMERIC', 'FUZZY', 'NONE')),
  CONSTRAINT ck_fields_confidence CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
  CONSTRAINT ck_fields_source CHECK (source IN ('MODEL', 'REVIEWER', 'EINVOICE'))
);
CREATE UNIQUE INDEX fields_current_uq ON fields (doc_id, name) WHERE is_current;

CREATE TABLE line_items (
  row_id       bigserial PRIMARY KEY,
  doc_id       uuid NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
  line_no      int NOT NULL CHECK (line_no >= 1),
  description  text,
  quantity     numeric,
  unit         text,
  days         numeric,
  unit_price   numeric,
  amount       numeric(14,2),
  source       text NOT NULL,
  is_current   boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_line_items_source CHECK (source IN ('MODEL', 'REVIEWER', 'EINVOICE'))
);
CREATE UNIQUE INDEX line_items_current_uq ON line_items (doc_id, line_no) WHERE is_current;

CREATE TABLE coding_lines (
  row_id           bigserial PRIMARY KEY,
  doc_id           uuid NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
  line_no          int NOT NULL CHECK (line_no >= 1),
  gl_account       text REFERENCES gl_accounts (code),
  cost_center      text REFERENCES cost_centers (code),
  tax_code         text REFERENCES tax_codes (code),
  net_amount       numeric(14,2) NOT NULL,
  tax_amount       numeric(14,2) NOT NULL,
  description      text,
  source_line_nos  int[] NOT NULL DEFAULT '{}',
  coding_source    text NOT NULL,
  is_current       boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_coding_lines_coding_source CHECK (coding_source IN ('PO', 'VENUE',
    'VENDOR_DEFAULT', 'REVIEWER', 'NONE'))
);
CREATE UNIQUE INDEX coding_lines_current_uq ON coding_lines (doc_id, line_no) WHERE is_current;

CREATE TABLE findings (
  finding_id    bigserial PRIMARY KEY,
  doc_id        uuid NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
  run_id        text NOT NULL,
  stage         text NOT NULL,
  rule_id       text NOT NULL CHECK (rule_id ~ '^R[0-9]{2}$'),
  rule_version  text NOT NULL,
  severity      text NOT NULL,
  scope         text NOT NULL,
  field         text,
  message       text NOT NULL,
  evidence      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_findings_severity CHECK (severity IN ('INFO', 'FLAG', 'HOLD', 'MANUAL')),
  CONSTRAINT ck_findings_scope CHECK (scope IN ('FIELD', 'DOCUMENT')),
  CONSTRAINT ck_findings_stage CHECK (stage IN ('INTAKE', 'REVIEW', 'EXPORT'))
);
CREATE INDEX findings_doc_idx ON findings (doc_id, run_id);

CREATE TABLE reviews (
  review_id   bigserial PRIMARY KEY,
  doc_id      uuid NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
  reviewer    text NOT NULL CHECK (length(trim(reviewer)) > 0),
  action      text NOT NULL,
  field       text,
  old_value   text,
  new_value   text,
  comment     text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_reviews_action CHECK (action IN ('CONFIRM', 'CORRECT', 'RECODE', 'APPROVE',
    'REJECT', 'RELEASE_HOLD')),
  CONSTRAINT ck_reviews_hold_comment CHECK (action <> 'RELEASE_HOLD'
    OR length(trim(coalesce(comment, ''))) > 0)
);

-- ------------------------------------------------------------------- gold
CREATE TABLE export_batches (
  batch_id         text PRIMARY KEY,
  created_at       timestamptz NOT NULL DEFAULT now(),
  csv_path         text NOT NULL,
  csv_sha256       char(64) NOT NULL,
  row_count        int NOT NULL CHECK (row_count >= 0),
  total            numeric(14,2) NOT NULL,
  layout           text NOT NULL,
  mapping_version  text NOT NULL,
  manifest         jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- One row per exported invoice. UNIQUE (doc_id) is what makes export-once hold.
CREATE TABLE export_rows (
  batch_id  text NOT NULL REFERENCES export_batches (batch_id),
  doc_id    uuid NOT NULL UNIQUE REFERENCES documents (doc_id),
  first_row_no  int NOT NULL CHECK (first_row_no >= 1),
  row_count     int NOT NULL CHECK (row_count >= 1),
  PRIMARY KEY (batch_id, doc_id)
);

CREATE TABLE notifications (
  notification_id  bigserial PRIMARY KEY,
  created_at       timestamptz NOT NULL DEFAULT now(),
  kind             text NOT NULL,
  message          text NOT NULL,
  batch_id         text REFERENCES export_batches (batch_id),
  read_at          timestamptz
);

-- -------------------------------------------------------------- audit log
CREATE TABLE events (
  event_id  bigserial PRIMARY KEY,
  ts        timestamptz NOT NULL DEFAULT now(),
  actor     text NOT NULL,
  doc_id    uuid,
  type      text NOT NULL,
  payload   jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE FUNCTION events_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'events is append-only';
END;
$$;

CREATE TRIGGER events_no_change BEFORE UPDATE OR DELETE ON events
  FOR EACH ROW EXECUTE FUNCTION events_append_only();
