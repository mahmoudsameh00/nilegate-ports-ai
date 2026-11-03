-- =====================================================================
-- 020 — Vessel performance parameters + the dated bunker price (Agents plan §6a S4; P9-1, P9-3, P9-5; D-P9-4…6)
-- Reference data for the Stage 2 tool vessel_params (route_advice, Phase 10): sea days = distance / speed, fuel per
-- day = main × (speed / ref_speed)³ + aux, fuel cost in SDR = tonnes × the dated VLSFO price / USD per SDR.
--   vessel_performance — 13 tariff categories × 3 SCNT size bands (tertiles of our vessels per category, band 1 from
--     0, band 3 open), each band mapped by rank to one size bin of the Fourth IMO GHG Study 2020, Table 35 (2018):
--     main_t_per_day = main-engine kt × 1,000 / days at sea; aux_t_per_day = auxiliary kt × 1,000 / 365;
--     ref_speed_kn = the bin's average speed over ground at sea. The raw IMO figures stay beside the derived ones.
--   bunker_prices — one dated VLSFO price in USD / t and the dated USD-per-SDR rate beside it (money in SDR,
--     ADR-003), set by the owner; a new price = a new row in a new migration (never an UPDATE).
-- Rendered from db/reference/vessel_performance.csv and bunker_prices.csv (39 + 1 rows); never edited after
-- applying. SELECT for tools through ports_readonly's default privileges (migration 007); not visible to finance_bi.
-- Both tables are level 1 / Operations (docs/rbac_mapping.md §2).
-- =====================================================================
BEGIN;

CREATE TABLE public.vessel_performance (
    vessel_type      text     NOT NULL,
    size_band        smallint NOT NULL,
    scnt_min         numeric  NOT NULL,
    scnt_max         numeric,
    imo_ship_type    text     NOT NULL,
    imo_size_bin     text     NOT NULL,
    imo_size_unit    text     NOT NULL,
    imo_days_at_sea  numeric  NOT NULL,
    imo_main_kt      numeric  NOT NULL,
    imo_aux_kt       numeric  NOT NULL,
    ref_speed_kn     numeric  NOT NULL,
    main_t_per_day   numeric  NOT NULL,
    aux_t_per_day    numeric  NOT NULL,
    source           text     NOT NULL,
    source_ref       text     NOT NULL,
    CONSTRAINT vessel_performance_pkey PRIMARY KEY (vessel_type, size_band),
    CONSTRAINT vessel_performance_vessel_type_chk CHECK (vessel_type IN (
        'Chemical Tankers & Other Liquid Bulk Tankers', 'Containerships', 'Crude Oil Tankers',
        'Cruise Ships', 'Dry Bulk Vessels', 'General Cargo / Multi-Purpose / Heavy Lift Vessels',
        'Liquefied Natural Gas (LNG) Carriers', 'Liquefied Petroleum Gas (LPG) Carriers', 'Other Vessels',
        'Petroleum Product Tankers', 'Roll-On/Roll-Off (Ro/Ro) Vessels', 'Special Floating Units',
        'Vehicles Carriers')),
    CONSTRAINT vessel_performance_size_band_chk CHECK (size_band BETWEEN 1 AND 3),
    CONSTRAINT vessel_performance_scnt_chk CHECK (scnt_min >= 0 AND (scnt_max IS NULL OR scnt_max > scnt_min)),
    CONSTRAINT vessel_performance_open_band_chk CHECK ((scnt_max IS NULL) = (size_band = 3)),
    CONSTRAINT vessel_performance_unit_chk CHECK (imo_size_unit IN ('dwt', 'teu', 'cbm', 'gt')),
    CONSTRAINT vessel_performance_positive_chk CHECK (imo_days_at_sea > 0 AND imo_days_at_sea <= 365 AND
        imo_main_kt > 0 AND imo_aux_kt >= 0 AND ref_speed_kn > 0 AND main_t_per_day > 0 AND aux_t_per_day >= 0)
);

INSERT INTO public.vessel_performance (vessel_type, size_band, scnt_min, scnt_max, imo_ship_type, imo_size_bin,
    imo_size_unit, imo_days_at_sea, imo_main_kt, imo_aux_kt, ref_speed_kn, main_t_per_day, aux_t_per_day, source,
    source_ref) VALUES
    ('Chemical Tankers & Other Liquid Bulk Tankers', 1, 0, 20000, 'Chemical tanker', '10000-19999', 'dwt', 190, 2.7, 0.8, 11.4, 14.2, 2.2, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Chemical tanker 10000-19999 dwt, printed p. 99'),
    ('Chemical Tankers & Other Liquid Bulk Tankers', 2, 20000, 47000, 'Chemical tanker', '20000-39999', 'dwt', 202, 4.5, 1.2, 12.1, 22.3, 3.3, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Chemical tanker 20000-39999 dwt, printed p. 99'),
    ('Chemical Tankers & Other Liquid Bulk Tankers', 3, 47000, NULL, 'Chemical tanker', '40000-+', 'dwt', 201, 4.7, 1.2, 11.9, 23.4, 3.3, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Chemical tanker 40000-+ dwt, printed p. 99'),
    ('Containerships', 1, 0, 89000, 'Container', '3000-4999', 'teu', 246, 12.7, 2.4, 14.7, 51.6, 6.6, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Container 3000-4999 teu, printed p. 99'),
    ('Containerships', 2, 89000, 153000, 'Container', '8000-11999', 'teu', 261, 26.4, 2.9, 16.3, 101.1, 7.9, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Container 8000-11999 teu, printed p. 99'),
    ('Containerships', 3, 153000, NULL, 'Container', '14500-19999', 'teu', 250, 26.7, 3.7, 16.5, 106.8, 10.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Container 14500-19999 teu, printed p. 99'),
    ('Crude Oil Tankers', 1, 0, 79000, 'Oil tanker', '80000-119999', 'dwt', 195, 5.4, 1.2, 11.2, 27.7, 3.3, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Oil tanker 80000-119999 dwt, printed p. 100'),
    ('Crude Oil Tankers', 2, 79000, 200000, 'Oil tanker', '120000-199999', 'dwt', 220, 8.0, 1.8, 11.4, 36.4, 4.9, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Oil tanker 120000-199999 dwt, printed p. 100'),
    ('Crude Oil Tankers', 3, 200000, NULL, 'Oil tanker', '200000-+', 'dwt', 252, 14.5, 1.7, 11.9, 57.5, 4.7, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Oil tanker 200000-+ dwt, printed p. 100'),
    ('Cruise Ships', 1, 0, 69000, 'Cruise', '10000-59999', 'gt', 206, 5.0, 6.4, 13.4, 24.3, 17.5, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Cruise 10000-59999 gt, printed p. 100'),
    ('Cruise Ships', 2, 69000, 104000, 'Cruise', '60000-99999', 'gt', 256, 16.1, 20.3, 15.3, 62.9, 55.6, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Cruise 60000-99999 gt, printed p. 100'),
    ('Cruise Ships', 3, 104000, NULL, 'Cruise', '100000-149999', 'gt', 250, 24.4, 20.0, 16.0, 97.6, 54.8, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Cruise 100000-149999 gt, printed p. 100'),
    ('Dry Bulk Vessels', 1, 0, 87000, 'Bulk carrier', '35000-59999', 'dwt', 184, 3.7, 0.4, 11.4, 20.1, 1.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Bulk carrier 35000-59999 dwt, printed p. 99'),
    ('Dry Bulk Vessels', 2, 87000, 153000, 'Bulk carrier', '60000-99999', 'dwt', 214, 4.9, 0.7, 11.4, 22.9, 1.9, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Bulk carrier 60000-99999 dwt, printed p. 99'),
    ('Dry Bulk Vessels', 3, 153000, NULL, 'Bulk carrier', '100000-199999', 'dwt', 252, 9.2, 0.7, 11.2, 36.5, 1.9, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Bulk carrier 100000-199999 dwt, printed p. 99'),
    ('General Cargo / Multi-Purpose / Heavy Lift Vessels', 1, 0, 24000, 'General cargo', '5000-9999', 'dwt', 176, 1.4, 0.3, 9.8, 8.0, 0.8, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'General cargo 5000-9999 dwt, printed p. 99'),
    ('General Cargo / Multi-Purpose / Heavy Lift Vessels', 2, 24000, 47000, 'General cargo', '10000-19999', 'dwt', 192, 2.8, 0.8, 11.4, 14.6, 2.2, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'General cargo 10000-19999 dwt, printed p. 99'),
    ('General Cargo / Multi-Purpose / Heavy Lift Vessels', 3, 47000, NULL, 'General cargo', '20000-+', 'dwt', 197, 4.5, 0.8, 11.9, 22.8, 2.2, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'General cargo 20000-+ dwt, printed p. 99'),
    ('Liquefied Natural Gas (LNG) Carriers', 1, 0, 76000, 'Liquefied gas tanker', '100000-199999', 'cbm', 271, 22.2, 4.4, 14.9, 81.9, 12.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Liquefied gas tanker 100000-199999 cbm, printed p. 99'),
    ('Liquefied Natural Gas (LNG) Carriers', 2, 76000, 136000, 'Liquefied gas tanker', '100000-199999', 'cbm', 271, 22.2, 4.4, 14.9, 81.9, 12.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Liquefied gas tanker 100000-199999 cbm, printed p. 99'),
    ('Liquefied Natural Gas (LNG) Carriers', 3, 136000, NULL, 'Liquefied gas tanker', '200000-+', 'cbm', 252, 26.3, 11.7, 16.0, 104.4, 32.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Liquefied gas tanker 200000-+ cbm, printed p. 99'),
    ('Liquefied Petroleum Gas (LPG) Carriers', 1, 0, 37000, 'Liquefied gas tanker', '0-49999', 'cbm', 190, 2.4, 0.4, 11.7, 12.6, 1.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Liquefied gas tanker 0-49999 cbm, printed p. 99'),
    ('Liquefied Petroleum Gas (LPG) Carriers', 2, 37000, 63000, 'Liquefied gas tanker', '50000-99999', 'cbm', 229, 8.9, 3.0, 14.1, 38.9, 8.2, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Liquefied gas tanker 50000-99999 cbm, printed p. 99'),
    ('Liquefied Petroleum Gas (LPG) Carriers', 3, 63000, NULL, 'Liquefied gas tanker', '50000-99999', 'cbm', 229, 8.9, 3.0, 14.1, 38.9, 8.2, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Liquefied gas tanker 50000-99999 cbm, printed p. 99'),
    ('Other Vessels', 1, 0, 15000, 'Miscellaneous - other', '0-+', 'gt', 102, 2.1, 0.4, 10.7, 20.6, 1.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Miscellaneous - other 0-+ gt, printed p. 101'),
    ('Other Vessels', 2, 15000, 29000, 'Miscellaneous - other', '0-+', 'gt', 102, 2.1, 0.4, 10.7, 20.6, 1.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Miscellaneous - other 0-+ gt, printed p. 101'),
    ('Other Vessels', 3, 29000, NULL, 'Miscellaneous - other', '0-+', 'gt', 102, 2.1, 0.4, 10.7, 20.6, 1.1, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Miscellaneous - other 0-+ gt, printed p. 101'),
    ('Petroleum Product Tankers', 1, 0, 54000, 'Oil tanker', '20000-59999', 'dwt', 166, 3.4, 1.0, 11.2, 20.5, 2.7, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Oil tanker 20000-59999 dwt, printed p. 100'),
    ('Petroleum Product Tankers', 2, 54000, 87000, 'Oil tanker', '60000-79999', 'dwt', 194, 5.2, 1.0, 11.6, 26.8, 2.7, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Oil tanker 60000-79999 dwt, printed p. 100'),
    ('Petroleum Product Tankers', 3, 87000, NULL, 'Oil tanker', '80000-119999', 'dwt', 195, 5.4, 1.2, 11.2, 27.7, 3.3, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Oil tanker 80000-119999 dwt, printed p. 100'),
    ('Roll-On/Roll-Off (Ro/Ro) Vessels', 1, 0, 28000, 'Ro-Ro', '5000-9999', 'dwt', 201, 6.1, 1.4, 14.2, 30.3, 3.8, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Ro-Ro 5000-9999 dwt, printed p. 101'),
    ('Roll-On/Roll-Off (Ro/Ro) Vessels', 2, 28000, 51000, 'Ro-Ro', '10000-14999', 'dwt', 218, 10.0, 1.9, 15.5, 45.9, 5.2, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Ro-Ro 10000-14999 dwt, printed p. 101'),
    ('Roll-On/Roll-Off (Ro/Ro) Vessels', 3, 51000, NULL, 'Ro-Ro', '15000-+', 'dwt', 199, 11.1, 1.8, 15.2, 55.8, 4.9, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Ro-Ro 15000-+ dwt, printed p. 101'),
    ('Special Floating Units', 1, 0, 58000, 'Offshore', '0-+', 'gt', 80, 0.6, 0.5, 8.5, 7.5, 1.4, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Offshore 0-+ gt, printed p. 101'),
    ('Special Floating Units', 2, 58000, 76000, 'Offshore', '0-+', 'gt', 80, 0.6, 0.5, 8.5, 7.5, 1.4, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Offshore 0-+ gt, printed p. 101'),
    ('Special Floating Units', 3, 76000, NULL, 'Offshore', '0-+', 'gt', 80, 0.6, 0.5, 8.5, 7.5, 1.4, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Offshore 0-+ gt, printed p. 101'),
    ('Vehicles Carriers', 1, 0, 38000, 'Vehicle', '0-29999', 'gt', 213, 4.6, 0.9, 13.6, 21.6, 2.5, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Vehicle 0-29999 gt, printed p. 101'),
    ('Vehicles Carriers', 2, 38000, 51000, 'Vehicle', '30000-49999', 'gt', 254, 7.1, 1.0, 14.7, 28.0, 2.7, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Vehicle 30000-49999 gt, printed p. 101'),
    ('Vehicles Carriers', 3, 51000, NULL, 'Vehicle', '50000-+', 'gt', 281, 10.4, 0.9, 15.5, 37.0, 2.5, 'Fourth IMO GHG Study 2020 (IMO, 2021), Table 35 - Detailed results for 2018', 'Vehicle 50000-+ gt, printed p. 101');

CREATE TABLE public.bunker_prices (
    fuel             text    NOT NULL,
    price_usd_per_t  numeric NOT NULL,
    price_date       date    NOT NULL,
    price_source     text    NOT NULL,
    usd_per_sdr      numeric NOT NULL,
    rate_date        date    NOT NULL,
    rate_source      text    NOT NULL,
    set_by           text    NOT NULL,
    CONSTRAINT bunker_prices_pkey PRIMARY KEY (fuel, price_date),
    CONSTRAINT bunker_prices_fuel_chk CHECK (fuel IN ('VLSFO')),
    CONSTRAINT bunker_prices_positive_chk CHECK (price_usd_per_t > 0 AND usd_per_sdr > 0)
);

INSERT INTO public.bunker_prices (fuel, price_usd_per_t, price_date, price_source, usd_per_sdr, rate_date,
    rate_source, set_by) VALUES
    ('VLSFO', 936.50, DATE '2026-10-26', 'Ship & Bunker, Global 20 Ports Average (G20) VLSFO, https://shipandbunker.com/prices', 1.354820, DATE '2026-10-26', 'IMF, SDR Valuation (SDR1 = US$), https://www.imf.org/external/np/fin/data/rms_sdrv.aspx', 'owner');

COMMENT ON TABLE public.vessel_performance IS 'Fuel and speed parameters per tariff vessel category and SCNT size band (Fourth IMO GHG Study 2020, Table 35, 2018 fleet), read by the Stage 2 tool vessel_params; level 1 / Operations (migration 020)';
COMMENT ON COLUMN public.vessel_performance.vessel_type IS 'tariff vessel category (the 13 values of vessels.vessel_type, ADR-033)';
COMMENT ON COLUMN public.vessel_performance.size_band IS '1 small / 2 medium / 3 large: tertiles of our vessels'' SCNT in the category';
COMMENT ON COLUMN public.vessel_performance.scnt_min IS 'band lower bound in SCNT tons (inclusive; band 1 starts at 0)';
COMMENT ON COLUMN public.vessel_performance.scnt_max IS 'band upper bound in SCNT tons (exclusive); NULL for the open band 3';
COMMENT ON COLUMN public.vessel_performance.imo_ship_type IS 'IMO ship type the band is mapped to (rank mapping; SCNT is not convertible to dwt / TEU / cbm)';
COMMENT ON COLUMN public.vessel_performance.imo_size_bin IS 'IMO size bin of that ship type (in imo_size_unit)';
COMMENT ON COLUMN public.vessel_performance.imo_size_unit IS 'unit of the IMO size bin: dwt, teu, cbm or gt';
COMMENT ON COLUMN public.vessel_performance.imo_days_at_sea IS 'IMO: average days at sea per year (2018)';
COMMENT ON COLUMN public.vessel_performance.imo_main_kt IS 'IMO: average main-engine fuel consumption per vessel per year, thousand tonnes';
COMMENT ON COLUMN public.vessel_performance.imo_aux_kt IS 'IMO: average auxiliary-engine fuel consumption per vessel per year, thousand tonnes';
COMMENT ON COLUMN public.vessel_performance.ref_speed_kn IS 'IMO: average speed over ground at sea, knots — the speed main_t_per_day belongs to';
COMMENT ON COLUMN public.vessel_performance.main_t_per_day IS 'main-engine tonnes per sea day at ref_speed_kn = imo_main_kt × 1000 / imo_days_at_sea; scaled by (speed / ref_speed_kn)³';
COMMENT ON COLUMN public.vessel_performance.aux_t_per_day IS 'auxiliary tonnes per day = imo_aux_kt × 1000 / 365; independent of speed';
COMMENT ON COLUMN public.vessel_performance.source IS 'publication the IMO figures come from';
COMMENT ON COLUMN public.vessel_performance.source_ref IS 'IMO ship type, size bin and printed page of Table 35';
COMMENT ON TABLE public.bunker_prices IS 'Dated bunker price set by the owner with the dated USD-per-SDR rate beside it (Agents plan P9-3); money is reported in SDR (ADR-003); level 1 / Operations (migration 020)';
COMMENT ON COLUMN public.bunker_prices.fuel IS 'fuel grade (VLSFO only)';
COMMENT ON COLUMN public.bunker_prices.price_usd_per_t IS 'price in US dollars per metric tonne';
COMMENT ON COLUMN public.bunker_prices.price_date IS 'date the price was published';
COMMENT ON COLUMN public.bunker_prices.price_source IS 'where the price was read (publication + URL)';
COMMENT ON COLUMN public.bunker_prices.usd_per_sdr IS 'US dollars per SDR on rate_date (IMF SDR valuation); SDR per tonne = price_usd_per_t / usd_per_sdr';
COMMENT ON COLUMN public.bunker_prices.rate_date IS 'date of the IMF rate';
COMMENT ON COLUMN public.bunker_prices.rate_source IS 'where the rate was read (publication + URL)';
COMMENT ON COLUMN public.bunker_prices.set_by IS 'who set the row (the owner)';

COMMIT;
