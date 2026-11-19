-- 002_rate_evidence_percent: R03 evidence shows a GST rate as "9%", not "9.00" (2026-11-19).
-- New findings already store it that way (rules.base.fmt_percent); this rewrites older rows.
-- Money in the same evidence ("subtotal", "gst_amount") keeps its two decimals.
-- Running it again changes nothing: a value that already ends in "%" is left alone.

CREATE OR REPLACE FUNCTION pg_temp.as_percent(value text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN value IS NULL OR right(value, 1) = '%' THEN value
    WHEN value LIKE '%.%' THEN rtrim(rtrim(value, '0'), '.') || '%'
    ELSE value || '%'
  END
$$;

UPDATE findings
SET evidence = evidence || jsonb_build_object(
  'expected', pg_temp.as_percent(evidence ->> 'expected'),
  'found', pg_temp.as_percent(evidence ->> 'found')
)
WHERE rule_id = 'R03'
  AND field = 'gst_rate'
  AND evidence ? 'expected'
  AND evidence ? 'found';

UPDATE findings
SET evidence = evidence || jsonb_build_object(
  'rate_percent', pg_temp.as_percent(evidence ->> 'rate_percent')
)
WHERE rule_id = 'R03'
  AND evidence ? 'rate_percent';
