-- =====================================================================
-- Negative test of the integrity constraints (migration 006). Every statement is expected to FAIL; each runs in its
-- own transaction that is rolled back, so nothing is ever written. Prints one PASS / FAIL line per case.
--   docker cp db\check_constraints_reject.sql ports-postgres:/tmp/c.sql
--   docker exec ports-postgres psql -U postgres -d ports_logistics -X -q -f /tmp/c.sql
-- =====================================================================
CREATE OR REPLACE FUNCTION pg_temp.expect_reject(label text, stmt text) RETURNS text LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE stmt;
        RAISE EXCEPTION 'accepted';  -- reached only when the statement was NOT rejected
    EXCEPTION
        WHEN check_violation OR unique_violation OR foreign_key_violation OR not_null_violation THEN
            RETURN 'PASS  ' || label || '  (' || SQLERRM || ')';
        WHEN raise_exception THEN
            RETURN 'FAIL  ' || label || '  (accepted)';
    END;
END $$;

BEGIN;
SELECT pg_temp.expect_reject('vessel status outside the list', $q$UPDATE vessels SET status = 'Sunk' WHERE vessel_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('unknown vessel category', $q$UPDATE vessels SET vessel_type = 'Submarine' WHERE vessel_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('negative tonnage', $q$UPDATE vessels SET scnt_tons = -1 WHERE vessel_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('origin = destination', $q$UPDATE vessels SET destination_locode = origin_locode WHERE vessel_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('bad MMSI', $q$UPDATE vessels SET mmsi = '12' WHERE vessel_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('container size 30 ft', $q$UPDATE containers SET size_ft = 30 WHERE container_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('malformed container number', $q$UPDATE containers SET container_number = 'ABC123' WHERE container_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('invoice amount 0', $q$UPDATE invoices SET amount = 0 WHERE invoice_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('invoice status', $q$UPDATE invoices SET status = 'Lost' WHERE invoice_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('duplicate toll band key', $q$INSERT INTO toll_rate_bands (vessel_category, laden_ballast, band_order, band_label, band_min_tons, band_max_tons, rate_sdr_per_ton) SELECT vessel_category, laden_ballast, band_order, band_label, band_min_tons, band_max_tons, rate_sdr_per_ton FROM toll_rate_bands WHERE id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('role ceiling 4', $q$UPDATE roles SET allowed_sensitivity_level = 4 WHERE role_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('email outside @nilegate.com', $q$UPDATE employees SET email = 'x@gmail.com' WHERE employee_id = 1$q$)
UNION ALL SELECT pg_temp.expect_reject('connection country code', $q$UPDATE port_connections SET country1 = 'XX' WHERE ctid = (SELECT ctid FROM port_connections LIMIT 1)$q$)
UNION ALL SELECT pg_temp.expect_reject('port geom <> lon/lat', $q$UPDATE ports SET lon = lon + 1 WHERE locode = 'EGALY'$q$);
ROLLBACK;
