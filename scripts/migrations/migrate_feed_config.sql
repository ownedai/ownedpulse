-- migrate_feed_config.sql
-- Migrates feed_config from nocodb → knowledge_base, removes nocodb dependency
-- Run: docker exec -i postgres psql -U postgres -d knowledge_base < migrate_feed_config.sql

BEGIN;

-- 1. Add missing columns
ALTER TABLE feed_config
    ADD COLUMN IF NOT EXISTS authority        text,
    ADD COLUMN IF NOT EXISTS default_doc_type text,
    ADD COLUMN IF NOT EXISTS backfill_months  integer NOT NULL DEFAULT 12,
    ADD COLUMN IF NOT EXISTS priority         integer NOT NULL DEFAULT 10,
    ADD COLUMN IF NOT EXISTS ingest_to_rag    boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS last_success_ts  timestamptz,
    ADD COLUMN IF NOT EXISTS last_error       text,
    ADD COLUMN IF NOT EXISTS ich_page_hashes  jsonb,
    ADD COLUMN IF NOT EXISTS scraper_config   jsonb;

-- 2. Rename url → feed_url
ALTER TABLE feed_config RENAME COLUMN url TO feed_url;

-- 3. Fix feed_type CHECK constraint
ALTER TABLE feed_config DROP CONSTRAINT IF EXISTS feed_config_feed_type_check;
ALTER TABLE feed_config ADD CONSTRAINT feed_config_feed_type_check
    CHECK (feed_type IN ('rss','json_api','json_bulk','html_pagination'));

-- 4. Populate all columns from nocodb data
UPDATE feed_config SET
    authority        = n.authority,
    feed_url         = n.feed_url,
    feed_type        = n.feed_type,
    default_doc_type = n.default_doc_type,
    backfill_months  = n.backfill_months,
    enabled          = n.enabled,
    priority         = n.priority,
    ingest_to_rag    = n.ingest_to_rag,
    ich_page_hashes  = n.ich_page_hashes,
    scraper_config   = n.scraper_config
FROM (VALUES
    (
        'ema_reg_guidance', 'EMA',
        'https://www.ema.europa.eu/en/regulatory-and-procedural-guideline.xml',
        'json_bulk', 'guidance_pdf', 36, true, 40, true,
        NULL::jsonb,
        '{"notes":"EMA open data JSON bulk file. No pagination needed - single file download. Updated daily by EMA. Confirmed 2026-05-21.","method":"json_bulk_download","base_url":"https://www.ema.europa.eu/en/documents/report/general-json-report_en.json","date_fields":["first_published_date","last_updated_date"],"date_format":"DD/MM/YYYY","delay_seconds":0,"total_records":2045,"guideline_filter":"title OR url contains guideline"}'::jsonb
    ),
    (
        'ema_sci_guidelines', 'EMA',
        'https://www.ema.europa.eu/en/scientific-guidelines.xml',
        'json_bulk', 'guidance_pdf', 36, true, 30, true,
        NULL::jsonb,
        '{"notes":"EMA open data JSON bulk file. No pagination needed - single file download. Updated daily by EMA. Confirmed 2026-05-21.","method":"json_bulk_download","base_url":"https://www.ema.europa.eu/en/documents/report/general-json-report_en.json","date_fields":["first_published_date","last_updated_date"],"date_format":"DD/MM/YYYY","delay_seconds":0,"total_records":2045,"guideline_filter":"title OR url contains guideline"}'::jsonb
    ),
    (
        'fda_drugs', 'FDA',
        'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml',
        'rss', 'drug_approval', 12, true, 10, true,
        NULL::jsonb,
        '{"notes":"openFDA drugsfda endpoint. Paginate with skip/limit. 4834 records in 12mo window as of 2026-05-21.","method":"json_api_pagination","base_url":"https://api.fda.gov/drug/drugsfda.json","page_size":100,"date_field":"submissions.submission_status_date","date_format":"YYYYMMDD","delay_seconds":0.3}'::jsonb
    ),
    (
        'fda_press_releases', 'FDA',
        'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml',
        'html_pagination', 'press_release', 12, true, 20, true,
        NULL::jsonb,
        '{"notes":"Drupal views page. 10 items per page. Pagination via ?page=N.","method":"html_pagination","base_url":"https://www.fda.gov/news-events/newsroom/press-announcements","href_filter":"press-announcements","date_pattern":"^(\\w+ \\d+,\\s*\\d{4})\\s*[-]\\s*(.+)$","delay_seconds":2.0,"article_selector":"div.view-content a[href]","pagination_param":"page"}'::jsonb
    ),
    (
        'ich_guidelines', 'ICH',
        'https://www.ich.org/page/ich-guidelines',
        'json_api', 'guidance_pdf', 60, true, 50, true,
        '{"/page/safety-guidelines":"687f43a9b8c7f7de0c47ba370013cc2b94ff2abfc75b8ca8eb06ccc43579b50f","/page/quality-guidelines":"6e779832d8d30fc553e403916c9e3ca3ac1a8507d140f63741435982b85f678d","/page/efficacy-guidelines":"bb2c18c00c3aa0a2fe27cb24948c25faa5467731bcc8aee3d08f9eb8356ba42f","/page/multidisciplinary-guidelines":"ecd2dba31818f78bb862ef31b5323c2339cd5a46d478953a845f995602d2adce"}'::jsonb,
        '{"notes":"admin.ich.org Drupal JSON API. 160 items as of 2026-05-21. Change detection via ich_page_hashes column.","method":"json_api_subdivisions","base_url":"https://admin.ich.org/api/v1/nodes","subdivisions":["/page/quality-guidelines","/page/safety-guidelines","/page/efficacy-guidelines","/page/multidisciplinary-guidelines"],"delay_seconds":0.5,"change_detection":"sha256_per_subdivision"}'::jsonb
    )
) AS n(feed_id, authority, feed_url, feed_type, default_doc_type,
       backfill_months, enabled, priority, ingest_to_rag,
       ich_page_hashes, scraper_config)
WHERE feed_config.feed_id = n.feed_id;

-- 5. Verify
SELECT feed_id, authority, feed_url, feed_type, default_doc_type,
       backfill_months, priority, ingest_to_rag,
       ich_page_hashes IS NOT NULL AS has_hashes,
       scraper_config IS NOT NULL AS has_scraper
FROM feed_config ORDER BY priority;

COMMIT;
