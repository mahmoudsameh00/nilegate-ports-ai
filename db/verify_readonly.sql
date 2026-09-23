-- ============================================================
-- Read-only verification of ports_logistics
-- Every transaction in this session is forced READ ONLY:
-- any INSERT/UPDATE/DELETE/DDL would fail, nothing can change.
-- ============================================================
SET default_transaction_read_only = on;
\pset pager off
\pset null '<NULL>'

\echo '### 0. SERVER / EXTENSIONS / SCHEMAS / DB USERS'
SELECT version();
SHOW default_transaction_read_only;
SELECT extname, extversion FROM pg_extension ORDER BY 1;
SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema' ORDER BY 1;
SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolname NOT LIKE 'pg\_%' ORDER BY 1;

\echo '### 1. TABLES + EXACT ROW COUNTS (public)'
SELECT table_name,
       (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint AS row_count
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY 1;
SELECT to_regclass('public.accepted_currencies') AS accepted_currencies_exists,
       to_regclass('public.audit_log')          AS audit_log_exists,
       to_regclass('public.documents')          AS documents_exists;

\echo '### 2. COLUMNS (exact types, nullability, defaults)'
SELECT c.relname AS table_name, a.attnum AS pos, a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       a.attnotnull AS not_null,
       pg_get_expr(d.adbin, d.adrelid) AS default_value
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
  AND c.relname <> 'spatial_ref_sys'
ORDER BY 1, 2;

\echo '### 3. CONSTRAINTS (PK / FK / UNIQUE / CHECK)'
SELECT conrelid::regclass AS table_name, contype, conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace AND conrelid::regclass::text <> 'spatial_ref_sys'
ORDER BY 1, 2, 3;

\echo '### 4. INDEXES'
SELECT tablename, indexname, indexdef FROM pg_indexes
WHERE schemaname = 'public' AND tablename <> 'spatial_ref_sys' ORDER BY 1, 2;

\echo '### 5. VIEWS / SEQUENCES / TRIGGERS'
SELECT viewname FROM pg_views WHERE schemaname = 'public' AND viewname NOT IN ('geography_columns','geometry_columns') ORDER BY 1;
SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = 'public' ORDER BY 1;
SELECT event_object_table, trigger_name, action_timing, event_manipulation FROM information_schema.triggers WHERE trigger_schema = 'public' ORDER BY 1, 2;

\echo '### 6. REFERENCE TABLE CONTENTS'
TABLE roles;
TABLE departments;

\echo '### 7. SAMPLE ROWS'
SELECT * FROM ports LIMIT 2;
SELECT port1_locode, port2_locode, flows, country1, country2 FROM port_connections LIMIT 2;
SELECT * FROM toll_rate_bands ORDER BY 1 LIMIT 3;
SELECT * FROM employees LIMIT 3;
SELECT * FROM vessels LIMIT 3;
SELECT * FROM containers LIMIT 3;
SELECT * FROM invoices LIMIT 3;

\echo '### 8. GEOMETRY CHECKS'
SELECT 'ports' AS t, ST_SRID(geom) AS srid, GeometryType(geom) AS gtype, count(*) FROM ports GROUP BY 2, 3
UNION ALL
SELECT 'port_connections', ST_SRID(geom), GeometryType(geom), count(*) FROM port_connections GROUP BY 2, 3;
SELECT count(*) AS ports_lonlat_vs_geom_mismatch FROM ports
WHERE abs(ST_X(geom) - lon) > 1e-9 OR abs(ST_Y(geom) - lat) > 1e-9;

\echo '### 9. REFERENTIAL CHECKS (orphans even if no FK exists)'
SELECT count(*) AS vessels_bad_origin      FROM vessels v    WHERE NOT EXISTS (SELECT 1 FROM ports p WHERE p.locode = v.origin_locode);
SELECT count(*) AS vessels_bad_destination FROM vessels v    WHERE NOT EXISTS (SELECT 1 FROM ports p WHERE p.locode = v.destination_locode);
SELECT count(*) AS containers_bad_origin   FROM containers c WHERE NOT EXISTS (SELECT 1 FROM ports p WHERE p.locode = c.origin_locode);
SELECT count(*) AS containers_bad_dest     FROM containers c WHERE NOT EXISTS (SELECT 1 FROM ports p WHERE p.locode = c.destination_locode);
SELECT count(*) AS containers_route_differs_from_vessel
FROM containers c JOIN vessels v ON v.vessel_id = c.vessel_id
WHERE c.origin_locode <> v.origin_locode OR c.destination_locode <> v.destination_locode;
SELECT count(*) AS vessel_types_not_in_toll_bands FROM vessels v
WHERE NOT EXISTS (SELECT 1 FROM toll_rate_bands b WHERE b.vessel_category = v.vessel_type);
SELECT count(*) AS vessel_id_not_matching_csv_order FROM vessels
WHERE vessel_id <> (imo_number::text::bigint - 9000000);

\echo '### 10. EMPLOYEES / RBAC'
SELECT role_id, department_id, count(*) FROM employees GROUP BY 1, 2 ORDER BY 1, 2;
SELECT count(*) - count(DISTINCT email) AS duplicate_emails FROM employees;

\echo '### 11. TOLL BAND CONSISTENCY'
SELECT vessel_category, laden_ballast, count(*) AS bands, min(band_order), max(band_order),
       count(*) FILTER (WHERE band_max_tons IS NULL) AS open_ended
FROM toll_rate_bands GROUP BY 1, 2 ORDER BY 1, 2;
SELECT b1.id, b1.vessel_category, b1.laden_ballast, b1.band_order, b1.band_max_tons, b2.band_min_tons AS next_min
FROM toll_rate_bands b1
JOIN toll_rate_bands b2 ON b2.vessel_category = b1.vessel_category AND b2.laden_ballast = b1.laden_ballast AND b2.band_order = b1.band_order + 1
WHERE b1.band_max_tons IS DISTINCT FROM b2.band_min_tons;

\echo '### 12. INVOICE CONSISTENCY (reverse-engineering how invoices were built)'
WITH x AS (
  SELECT i.*, v.vessel_type, v.scnt_tons AS vessel_scnt,
         CASE WHEN v.vessel_type = 'Special Floating Units' THEN 'Laden' ELSE v.condition END AS eff_condition,
         b.vessel_category, b.laden_ballast, b.band_min_tons, b.band_max_tons, b.rate_sdr_per_ton AS band_rate
  FROM invoices i
  JOIN vessels v ON v.vessel_id = i.vessel_id
  LEFT JOIN toll_rate_bands b ON b.id = i.toll_rate_band_id
)
SELECT count(*)                                                                   AS invoices,
       count(*) FILTER (WHERE toll_rate_band_id IS NULL)                          AS no_band,
       count(*) FILTER (WHERE scnt_tons <> vessel_scnt)                           AS scnt_differs_from_vessel,
       count(*) FILTER (WHERE vessel_category <> vessel_type)                     AS band_category_mismatch,
       count(*) FILTER (WHERE laden_ballast <> eff_condition)                     AS band_condition_mismatch,
       count(*) FILTER (WHERE rate_sdr_per_ton IS DISTINCT FROM band_rate)        AS rate_differs_from_band,
       count(*) FILTER (WHERE NOT (scnt_tons > band_min_tons AND (band_max_tons IS NULL OR scnt_tons <= band_max_tons))) AS scnt_outside_band
FROM x;
WITH calc AS (
  SELECT i.invoice_id, i.amount,
         round(sum(GREATEST(0, LEAST(i.scnt_tons, COALESCE(b.band_max_tons, i.scnt_tons)) - b.band_min_tons) * b.rate_sdr_per_ton)::numeric, 2) AS recomputed
  FROM invoices i
  JOIN vessels v ON v.vessel_id = i.vessel_id
  JOIN toll_rate_bands b ON b.vessel_category = v.vessel_type
   AND b.laden_ballast = CASE WHEN v.vessel_type = 'Special Floating Units' THEN 'Laden' ELSE v.condition END
  GROUP BY i.invoice_id, i.amount
)
SELECT count(*) AS checked, count(*) FILTER (WHERE abs(amount - recomputed) > 0.01) AS amount_mismatch,
       max(abs(amount - recomputed)) AS max_abs_diff
FROM calc;
SELECT status, count(*) FROM invoices GROUP BY 1 ORDER BY 1;
SELECT min(invoice_date), max(invoice_date) FROM invoices;

\echo '### END'
