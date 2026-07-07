-- Add fda_guidance_catalogue feed to feed_config + extend feed_type constraint.
-- Required for the json_static feed type introduced in Phase H.
-- Safe to re-run — uses IF NOT EXISTS / ON CONFLICT DO NOTHING.

DO $$
BEGIN
    -- Extend feed_type constraint to allow json_static
    ALTER TABLE feed_config DROP CONSTRAINT IF EXISTS feed_config_feed_type_check;
    ALTER TABLE feed_config ADD CONSTRAINT feed_config_feed_type_check
        CHECK (feed_type IN ('rss','json_api','json_bulk','html_pagination','json_static'));
EXCEPTION WHEN duplicate_object THEN
    NULL;  -- constraint already updated
END $$;

INSERT INTO feed_config (feed_id, name, feed_url, feed_type, enabled)
VALUES (
    'fda_guidance_catalogue',
    'FDA Guidance Documents',
    'https://www.fda.gov/files/api/datatables/static/search-for-guidance.json',
    'json_static',
    true
)
ON CONFLICT (feed_id) DO NOTHING;
