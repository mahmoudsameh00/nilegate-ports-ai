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

\echo '### 13. VESSEL MMSI (migrations 004-005, ADR-028)'
-- expected: 500 | 500 | 0 | 0 | 0 | 0  (rows, distinct, null, bad format, flags with >1 MID, formula mismatches)
SELECT count(*)                                                        AS vessels,
       count(DISTINCT mmsi)                                            AS distinct_mmsi,
       count(*) FILTER (WHERE mmsi IS NULL)                            AS null_mmsi,
       count(*) FILTER (WHERE mmsi !~ '^[2-7][0-9]{8}$')               AS bad_format,
       (SELECT count(*) FROM (SELECT flag_country FROM vessels GROUP BY 1
                              HAVING count(DISTINCT left(mmsi, 3)) > 1) x) AS flags_with_several_mids,
       count(*) FILTER (WHERE right(mmsi, 6) <> lpad(((vessel_id * 7919 + 42) % 1000000)::text, 6, '0'))
                                                                       AS formula_mismatch
FROM vessels;

\echo '### 14. INTEGRITY CONSTRAINTS AND INDEXES (migration 006, ADR-033)'
-- expected: CHECK per table (containers 5, documents 5, employees 1, invoices 5, port_connections 3, ports 6, roles 1,
--           toll_rate_bands 5, vessels 7), toll_rate_bands_band_key present, every FK column indexed, 2 GIST indexes
SELECT conrelid::regclass AS tbl, count(*) FILTER (WHERE contype = 'c') AS checks, count(*) FILTER (WHERE contype = 'u') AS uniques,
       count(*) FILTER (WHERE contype = 'f') AS fks
FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND conrelid <> 'spatial_ref_sys'::regclass
GROUP BY 1 ORDER BY 1::text;
SELECT count(*) AS fk_columns_without_index
FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
  AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = a.attnum);
SELECT indexrelid::regclass AS gist_index FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_am am ON am.oid = c.relam WHERE am.amname = 'gist' AND i.indrelid IN ('ports'::regclass, 'port_connections'::regclass) ORDER BY 1::text;
-- expected 0: port_connections.country1/2 are the LOCODE prefixes (ISO alpha-2), ports.country holds names
SELECT count(*) AS connection_country_code_mismatch FROM port_connections
WHERE country1 <> left(port1_locode, 2) OR country2 <> left(port2_locode, 2);

\echo '### 15. ACCESS, DOCUMENTATION, STATISTICS (migrations 007-009, ADR-033, ADR-034)'
SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY 1;
SELECT count(*) FILTER (WHERE has_table_privilege('ports_readonly', c.oid, 'SELECT')) AS readonly_can_select,
       count(*) FILTER (WHERE has_table_privilege('ports_readonly', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')) AS readonly_can_write,
       count(*) AS public_tables
FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r';
-- expected 0 | 0: every public table and every column (except the PostGIS system table) has a comment
SELECT count(*) FILTER (WHERE obj_description(c.oid, 'pg_class') IS NULL) AS tables_without_comment,
       (SELECT count(*) FROM pg_attribute a JOIN pg_class t ON t.oid = a.attrelid
        WHERE t.relnamespace = 'public'::regnamespace AND t.relkind = 'r' AND t.relname <> 'spatial_ref_sys'
          AND a.attnum > 0 AND NOT a.attisdropped AND col_description(t.oid, a.attnum) IS NULL) AS columns_without_comment
FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r' AND c.relname <> 'spatial_ref_sys';
-- expected 0: planner statistics exist for every project table
SELECT count(*) AS tables_never_analyzed FROM pg_stat_user_tables
WHERE schemaname = 'public' AND relname <> 'spatial_ref_sys' AND last_analyze IS NULL AND last_autoanalyze IS NULL;

\echo '### 16. RAG DOCUMENT REGISTRY (migrations 010-011, ADR-035)'
-- expected: 29 | 2163 | 765 | 29 | 29 | 29  (ingested_into_qdrant: 0 before migration 011)
SELECT count(*) AS documents, sum(chunk_count) AS chunks, sum(page_count) AS pages, count(DISTINCT sha256) AS distinct_sha256,
       count(*) FILTER (WHERE ingested_at IS NOT NULL) AS ingested_into_qdrant,
       count(*) FILTER (WHERE document_id ~ '^[a-z0-9_]+$') AS slug_format_ok
FROM documents;
SELECT p.department_name, d.sensitivity_level, count(*) FROM documents d JOIN departments p USING (department_id) GROUP BY 1, 2 ORDER BY 1, 2;

\echo '### 17. FINANCE DATA (migration 012, Agents plan §4a)'
-- expected: 40 | 500 | 994 | 0 | 0 | 0 | 676 | 88 | 52
SELECT (SELECT count(*) FROM customers) AS customers,
       (SELECT count(*) FROM vessels WHERE customer_id IS NOT NULL) AS vessels_with_customer,
       (SELECT count(*) FROM payments) AS payments,
       (SELECT count(*) FROM payments p JOIN invoices i USING (invoice_number) WHERE p.amount_sdr <> i.amount) AS payment_amount_mismatch,
       (SELECT count(*) FROM payments p JOIN invoices i USING (invoice_number) WHERE p.paid_date < i.invoice_date) AS paid_before_invoice,
       (SELECT count(*) FROM payments WHERE paid_date > DATE '2026-03-31') AS paid_after_horizon,
       (SELECT count(*) FROM budget_weekly) AS budget_rows,
       (SELECT count(*) FROM finance_test.invoices) AS test_invoices,
       (SELECT count(*) FROM finance_test.budget_weekly) AS test_budget_rows;
-- expected: 6 segments; every customer has at least one vessel; terms 30 / 45 / 60
SELECT c.segment, count(DISTINCT c.customer_id) AS customers, count(v.vessel_id) AS vessels
FROM customers c LEFT JOIN vessels v USING (customer_id) GROUP BY 1 ORDER BY 1;

\echo '### 18. FINANCE VIEWS (migrations 013-014, Agents plan Phases 2-3)'
-- expected: 14 | 0 | 0 | 455 | 52 | 1000 | 994 | 4 | 13 | 598  (12 views before 014, 13 before 015)
SELECT (SELECT count(*) FROM pg_class WHERE relnamespace = 'finance'::regnamespace AND relkind = 'v') AS finance_views,
       (SELECT count(*) FROM pg_class c WHERE c.relnamespace = 'finance'::regnamespace AND c.relkind = 'v'
          AND obj_description(c.oid, 'pg_class') IS NULL) AS views_without_comment,
       (SELECT count(*) FROM pg_attribute a JOIN pg_class t ON t.oid = a.attrelid
        WHERE t.relnamespace = 'finance'::regnamespace AND t.relkind = 'v' AND a.attnum > 0 AND NOT a.attisdropped
          AND col_description(t.oid, a.attnum) IS NULL) AS columns_without_comment,
       (SELECT count(*) FROM finance.dim_date) AS dim_date_days,
       (SELECT count(*) FROM finance.kpi_weekly) AS kpi_weeks,
       (SELECT count(*) FROM finance.fact_invoice) AS fact_invoices,
       (SELECT count(*) FROM finance.fact_payment) AS fact_payments,
       (SELECT count(*) FROM finance.fact_invoice WHERE invoice_report_week IS NULL) AS invoices_in_2026_w01,
       (SELECT count(*) FROM finance.kpi_weekly WHERE is_warmup) AS warmup_weeks,
       (SELECT count(*) FROM finance.kpi_weekly_trend) AS trend_rows;
-- expected 14 | 0 | 0 (13 before 015): finance_bi reads the finance views, writes nothing, reads nothing outside schema finance
-- (PostGIS grants SELECT on its own catalog objects to PUBLIC; they are excluded)
SELECT count(*) FILTER (WHERE c.relnamespace = 'finance'::regnamespace AND has_table_privilege('finance_bi', c.oid, 'SELECT')) AS bi_finance_select,
       count(*) FILTER (WHERE has_table_privilege('finance_bi', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')) AS bi_write,
       count(*) FILTER (WHERE c.relnamespace <> 'finance'::regnamespace AND has_table_privilege('finance_bi', c.oid, 'SELECT')) AS bi_outside_finance
FROM pg_class c
WHERE c.relnamespace IN ('finance'::regnamespace, 'public'::regnamespace, 'finance_test'::regnamespace) AND c.relkind IN ('r', 'v')
  AND c.relname NOT IN ('spatial_ref_sys', 'geometry_columns', 'geography_columns');
-- expected ≤ 0.02 (rounded inputs): AR(w) = AR(w−1) + billed(w) − collected(w) on all 52 weeks
SELECT max(abs(coalesce(prev_ar, 0) + billed_sdr - collected_sdr - ar_sdr)) AS ar_roll_forward_max_diff
FROM (SELECT ar_sdr, billed_sdr, collected_sdr, lag(ar_sdr) OVER (ORDER BY report_week) AS prev_ar FROM finance.kpi_weekly) k;

\echo '### 19. INVOICE AUDIT VIEWS (migration 015, Agents plan Phase 4)'
-- expected: 3 | 3 | 0 | 0 | 0 | 0 | 5 | 1 | 1 | 1 | 1 | 1 | 0
-- live: the 3 reviewed same-vessel, same-day, same-amount pairs (ADR-013 data); test: the 5 planted errors with
-- their causes, nothing in clean week 49
SELECT (SELECT count(*) FROM finance.invoice_audit) AS live_findings,
       (SELECT count(*) FROM finance.invoice_audit WHERE check_code = 'duplicate_charge') AS live_duplicates,
       (SELECT count(*) FROM finance.invoice_audit WHERE check_code = 'amount_mismatch') AS live_amount,
       (SELECT count(*) FROM finance.invoice_audit WHERE check_code = 'tonnage_mismatch') AS live_tonnage,
       (SELECT count(*) FROM finance.invoice_audit WHERE check_code = 'rate_mismatch') AS live_rate,
       (SELECT count(*) FROM finance.invoice_audit WHERE report_week IS NULL) AS live_outside_weeks,
       (SELECT count(*) FROM finance_test.invoice_audit) AS test_findings,
       (SELECT count(*) FROM finance_test.invoice_audit WHERE probable_cause = 'flat_terminal_rate') AS test_flat_rate,
       (SELECT count(*) FROM finance_test.invoice_audit WHERE probable_cause = 'condition_swapped') AS test_cond_swap,
       (SELECT count(*) FROM finance_test.invoice_audit WHERE probable_cause = 'sfu_priced_ballast') AS test_sfu,
       (SELECT count(*) FROM finance_test.invoice_audit WHERE check_code = 'tonnage_mismatch') AS test_tonnage,
       (SELECT count(*) FROM finance_test.invoice_audit WHERE check_code = 'duplicate_charge') AS test_duplicates,
       (SELECT count(*) FROM finance_test.invoice_audit WHERE report_week = 49) AS test_week49;
-- expected t | f | t | t: Power BI reads the live audit only; the tools' role reads both
SELECT has_table_privilege('finance_bi', 'finance.invoice_audit', 'SELECT') AS bi_live,
       has_table_privilege('finance_bi', 'finance_test.invoice_audit', 'SELECT') AS bi_test,
       has_table_privilege('ports_readonly', 'finance.invoice_audit', 'SELECT') AS ro_live,
       has_table_privilege('ports_readonly', 'finance_test.invoice_audit', 'SELECT') AS ro_test;

\echo '### 20. AGENT STATE (migration 016, Agents plan Phase 5)'
-- expected: t | postgres | t | f | ports_agent | {search_path=agent_state} | f
-- (login: NULL / NULL before db/create_agent_user.ps1)
SELECT to_regnamespace('agent_state') IS NOT NULL AS schema_exists,
       (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'agent_state') AS schema_owner,
       EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_writer') AS writer_role,
       (SELECT rolcanlogin FROM pg_roles WHERE rolname = 'agent_writer') AS writer_can_login,
       (SELECT string_agg(r.rolname, ',') FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member
        WHERE m.roleid = (SELECT oid FROM pg_roles WHERE rolname = 'agent_writer')) AS writer_members,
       (SELECT s.setconfig::text FROM pg_db_role_setting s JOIN pg_roles r ON r.oid = s.setrole
        WHERE r.rolname = 'ports_agent') AS login_settings,
       has_schema_privilege('agent_writer', 'agent_state', 'CREATE') AS writer_can_create;
-- expected: 4 | 4 | 0 | 0 | 0 | 0 (0 | 0 | 0 | 0 | 0 | 0 before Checkpointer_setup.py): the checkpoint tables, DML for
-- agent_writer, no TRUNCATE, nothing for ports_readonly / finance_bi, nothing outside agent_state for the writer
SELECT count(*) FILTER (WHERE c.relnamespace = 'agent_state'::regnamespace) AS state_tables,
       count(*) FILTER (WHERE c.relnamespace = 'agent_state'::regnamespace
                          AND has_table_privilege('agent_writer', c.oid, 'SELECT')
                          AND has_table_privilege('agent_writer', c.oid, 'INSERT')
                          AND has_table_privilege('agent_writer', c.oid, 'UPDATE')
                          AND has_table_privilege('agent_writer', c.oid, 'DELETE')) AS writer_dml,
       count(*) FILTER (WHERE c.relnamespace = 'agent_state'::regnamespace
                          AND has_table_privilege('agent_writer', c.oid, 'TRUNCATE')) AS writer_truncate,
       count(*) FILTER (WHERE c.relnamespace = 'agent_state'::regnamespace
                          AND has_table_privilege('ports_readonly', c.oid, 'SELECT')) AS readonly_reads_state,
       count(*) FILTER (WHERE c.relnamespace = 'agent_state'::regnamespace
                          AND has_table_privilege('finance_bi', c.oid, 'SELECT')) AS bi_reads_state,
       count(*) FILTER (WHERE c.relnamespace <> 'agent_state'::regnamespace
                          AND c.relname NOT IN ('spatial_ref_sys', 'geometry_columns', 'geography_columns')
                          AND has_table_privilege('agent_writer', c.oid, 'SELECT,INSERT,UPDATE,DELETE')) AS writer_outside
FROM pg_class c
WHERE c.relkind IN ('r', 'v')
  AND c.relnamespace IN ('agent_state'::regnamespace, 'public'::regnamespace, 'finance'::regnamespace,
                         'finance_test'::regnamespace);

\echo '### 21. TWIN KPI VIEWS OF THE EVALUATION COPY (migration 017, Agents plan Phase 7)'
-- expected: 52 | 4 | 0 | 0 | 1 | -23600.00 | 598696.79 | -64363.84
-- category rows (4 weeks x 13) | weekly rows | clean week 49 differing from the live views (billed, budget) | other
-- columns differing from live | budget rows changed (week 36 LNG, the planted x 1.5) | billed test - live of weeks
-- 10 / 23 / 36 (the planted errors: wrong rate; duplicate + laden / ballast swap; SFU priced ballast)
SELECT (SELECT count(*) FROM finance_test.kpi_weekly_category) AS category_rows,
       (SELECT count(*) FROM finance_test.kpi_weekly) AS weekly_rows,
       (SELECT count(*) FROM finance_test.kpi_weekly t JOIN finance.kpi_weekly l USING (report_week)
        WHERE t.report_week = 49 AND (t.billed_sdr, t.budget_sdr, t.billed_wow_pct)
                                 IS DISTINCT FROM (l.billed_sdr, l.budget_sdr, l.billed_wow_pct)) AS week49_diff,
       (SELECT count(*) FROM finance_test.kpi_weekly t JOIN finance.kpi_weekly l USING (report_week)
        WHERE (t.ar_sdr, t.overdue_sdr, t.collected_sdr, t.dso_days, t.top10_share_13w_pct)
              IS DISTINCT FROM (l.ar_sdr, l.overdue_sdr, l.collected_sdr, l.dso_days, l.top10_share_13w_pct)) AS live_cols_diff,
       (SELECT count(*) FROM finance_test.kpi_weekly_category t
        JOIN finance.kpi_weekly_category l USING (report_week, vessel_category)
        WHERE t.budget_sdr <> l.budget_sdr) AS budget_rows_changed,
       (SELECT t.billed_sdr - l.billed_sdr FROM finance_test.kpi_weekly t JOIN finance.kpi_weekly l USING (report_week)
        WHERE report_week = 10) AS w10_billed_diff,
       (SELECT t.billed_sdr - l.billed_sdr FROM finance_test.kpi_weekly t JOIN finance.kpi_weekly l USING (report_week)
        WHERE report_week = 23) AS w23_billed_diff,
       (SELECT t.billed_sdr - l.billed_sdr FROM finance_test.kpi_weekly t JOIN finance.kpi_weekly l USING (report_week)
        WHERE report_week = 36) AS w36_billed_diff;
-- expected f | f | t | t: Power BI never sees the copy; the tools' read-only role reads both twins
SELECT has_table_privilege('finance_bi', 'finance_test.kpi_weekly', 'SELECT') AS bi_weekly,
       has_table_privilege('finance_bi', 'finance_test.kpi_weekly_category', 'SELECT') AS bi_category,
       has_table_privilege('ports_readonly', 'finance_test.kpi_weekly', 'SELECT') AS ro_weekly,
       has_table_privilege('ports_readonly', 'finance_test.kpi_weekly_category', 'SELECT') AS ro_category;

\echo '### END'
