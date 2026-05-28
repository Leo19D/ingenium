-- =============================================================================
-- Seed data — minimal sample for development & demo
-- =============================================================================
-- Run AFTER schema.sql

-- Demo organizacija
INSERT INTO organizations (id, name, slug, country_code, base_currency, locale, timezone)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Elektro Demo d.o.o.',
    'elektro-demo',
    'HR',
    'EUR',
    'hr-HR',
    'Europe/Zagreb'
) ON CONFLICT (slug) DO NOTHING;

-- Leo Dupanovic — owner account (lozinka se postavlja pri prvom loginu ili reset-om)
-- is_verified=true jer je vlasnik, ne treba verifikaciju
-- Lozinka: postaviti ćeš je kroz /api/v1/auth/register ili direktno ovdje kao hash
INSERT INTO users (id, email, full_name, auth_provider, hashed_password, locale, is_active, is_verified)
VALUES (
    '00000000-0000-0000-0000-000000000010',
    'leodupanovic1@gmail.com',
    'Leo Dupanovic',
    'local',
    '$2b$12$fyEtSb2rYSy6dl1UTrpGxeZRltJnqTtc1ZgKoA7wjFs76Y3CqCjGO',  -- demo123 (PROMIJENI!)
    'hr-HR',
    true,
    true
) ON CONFLICT (email) DO NOTHING;

INSERT INTO memberships (org_id, user_id, role)
VALUES ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000010', 'owner')
ON CONFLICT DO NOTHING;

-- Demo skladišne lokacije
INSERT INTO stock_locations (id, org_id, name, country_code)
VALUES (
    '00000000-0000-0000-0000-000000000100',
    '00000000-0000-0000-0000-000000000001',
    'Skladište RI',
    'HR'
) ON CONFLICT DO NOTHING;

-- Demo klijenti
INSERT INTO clients (org_id, name, tax_id, country_code, segment, payment_terms_days) VALUES
('00000000-0000-0000-0000-000000000001', 'Hotel Amabilis d.o.o.', 'HR12345678901', 'HR', 'hotel', 30),
('00000000-0000-0000-0000-000000000001', 'Konzum d.d.', 'HR98765432100', 'HR', 'retail', 45),
('00000000-0000-0000-0000-000000000001', 'HEP d.d.', 'HR11223344556', 'HR', 'public_sector', 60)
ON CONFLICT DO NOTHING;

-- Demo dobavljači
INSERT INTO suppliers (org_id, name, country_code, currency, incoterms_default, lead_time_days_avg, rating, on_time_rate) VALUES
('00000000-0000-0000-0000-000000000001', 'Fagerhult AB', 'SE', 'EUR', 'EXW', 7, 4.5, 0.94),
('00000000-0000-0000-0000-000000000001', 'Trilux GmbH', 'DE', 'EUR', 'DAP', 5, 4.2, 0.91),
('00000000-0000-0000-0000-000000000001', 'Osram GmbH', 'DE', 'EUR', 'FCA', 10, 4.3, 0.87),
('00000000-0000-0000-0000-000000000001', 'Prysmian Group', 'IT', 'EUR', 'EXW', 3, 4.6, 0.97)
ON CONFLICT DO NOTHING;

-- Demo produkti
INSERT INTO products (org_id, sku, name, category, brand, unit, specs) VALUES
('00000000-0000-0000-0000-000000000001', 'LED-PNL-6060-36-4K', 'LED Panel 60x60 36W 4000K', 'led_panel', 'generic', 'pcs',
    '{"wattage":36,"cct":4000,"lumen":3600,"ugr":19,"ip":20,"dimensions":"595x595"}'::jsonb),
('00000000-0000-0000-0000-000000000001', 'LED-DL-10W-3K-IP44-W', 'Downlight LED 10W 3000K IP44', 'downlight', 'generic', 'pcs',
    '{"wattage":10,"cct":3000,"lumen":900,"ip":44,"diameter":90,"color":"white"}'::jsonb),
('00000000-0000-0000-0000-000000000001', 'KBL-NYY-3X25-CRN', 'Kabel NYY-J 3x2.5mm² crni', 'cable', 'generic', 'm',
    '{"cross_section":"3x2.5","voltage":"0.6/1kV","color":"black","type":"NYY-J"}'::jsonb)
ON CONFLICT DO NOTHING;

-- Demo skladišno stanje
INSERT INTO stock_items (org_id, location_id, sku, name, category, unit, quantity_on_hand, min_stock_level, unit_cost, currency)
VALUES
('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000100',
    'LED-PNL-6060-36-4K', 'LED Panel 60x60 36W 4000K', 'led_panel', 'pcs', 142, 20, 18.40, 'EUR'),
('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000100',
    'LED-DL-10W-3K-IP44-W', 'Downlight LED 10W IP44', 'downlight', 'pcs', 386, 50, 6.20, 'EUR'),
('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000100',
    'KBL-NYY-3X25-CRN', 'NYY-J 3x2.5mm² crni', 'cable', 'm', 2840, 500, 1.42, 'EUR'),
('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000100',
    'DALI-CTRL-2CH', 'DALI kontroler 2ch', 'controller', 'pcs', 8, 15, 48.00, 'EUR'),
('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000100',
    'SPOT-GU10-7W-3K', 'Spot GU10 7W 3000K', 'spot', 'pcs', 42, 100, 4.20, 'EUR')
ON CONFLICT DO NOTHING;

-- Demo VAT pravila (osnovna EU)
INSERT INTO tax_rules (country_code, rule_type, rate, valid_from) VALUES
('HR', 'vat', 0.25, '2023-01-01'),
('SI', 'vat', 0.22, '2023-01-01'),
('DE', 'vat', 0.19, '2023-01-01'),
('IT', 'vat', 0.22, '2023-01-01'),
('AT', 'vat', 0.20, '2023-01-01'),
('FR', 'vat', 0.20, '2023-01-01')
ON CONFLICT DO NOTHING;

-- Demo FX (EUR baza, snapshot na današnji dan)
INSERT INTO fx_rates (base_ccy, quote_ccy, rate, source, as_of) VALUES
('EUR', 'USD', 1.0850, 'ecb', now()),
('EUR', 'GBP', 0.8420, 'ecb', now()),
('EUR', 'CHF', 0.9560, 'ecb', now()),
('EUR', 'HRK', 7.5345, 'manual', now())   -- fixed conversion rate
ON CONFLICT DO NOTHING;
