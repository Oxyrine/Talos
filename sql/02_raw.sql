-- 02_raw.sql: raw books. Append-only snapshots, one load per book per business date.
-- Load IDs look like LOS-20260930-01; a late correction is load -02 of the same
-- book and business date (a full snapshot with the changed rows).

CREATE TABLE IF NOT EXISTS RAW_LOS.CUSTOMER (
  cust_id VARCHAR(20) NOT NULL,
  cust_name VARCHAR(200) NOT NULL,
  pan VARCHAR(12),
  cin VARCHAR(24),
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  group_code VARCHAR(20),            -- stale annual group map (the reported baseline)
  director_dins VARCHAR(200),        -- semicolon-joined 8-digit DINs
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS RAW_LOS.LOAN (
  loan_id VARCHAR(20) NOT NULL,
  cust_id VARCHAR(20) NOT NULL,
  product VARCHAR(20) NOT NULL,      -- TERM_LOAN | WORKING_CAPITAL | CC_OD
  sanctioned_amt DECIMAL(18,2) NOT NULL,
  outstanding_amt DECIMAL(18,2) NOT NULL,
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS RAW_LOS.DEPENDENCY (
  cust_id VARCHAR(20) NOT NULL,
  depends_on_cust_id VARCHAR(20) NOT NULL,
  share_pct DECIMAL(5,2) NOT NULL,   -- share of the customer's revenue from or output to the other
  noted_on DATE NOT NULL,
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS RAW_TREASURY.HOLDING (
  holding_id VARCHAR(20) NOT NULL,
  issuer_ref VARCHAR(20) NOT NULL,
  issuer_name VARCHAR(200) NOT NULL,
  pan VARCHAR(12),
  cin VARCHAR(24),
  lei VARCHAR(24),
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  instrument VARCHAR(10) NOT NULL,   -- NCD | CP | BOND
  carrying_value DECIMAL(18,2) NOT NULL,
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS RAW_GUARANTEE.GUARANTEE (
  guarantee_id VARCHAR(20) NOT NULL,
  party_ref VARCHAR(20) NOT NULL,
  party_name VARCHAR(200) NOT NULL,
  pan VARCHAR(12),
  cin VARCHAR(24),
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  kind VARCHAR(4) NOT NULL,          -- FIN | PERF
  amount DECIMAL(18,2) NOT NULL,
  expiry_date DATE,
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS RAW_COLLATERAL.PLEDGE (
  pledge_id VARCHAR(20) NOT NULL,
  pledgor_ref VARCHAR(20) NOT NULL,
  pledgor_name VARCHAR(200) NOT NULL,
  pan VARCHAR(12),
  cin VARCHAR(24),
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  security_type VARCHAR(12) NOT NULL,
  pledge_value DECIMAL(18,2) NOT NULL,
  linked_loan_id VARCHAR(20),
  business_date DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS RAW_REGISTRY.ENTITY_FILING (
  cin VARCHAR(24) NOT NULL,
  pan VARCHAR(12),
  lei VARCHAR(24),
  entity_name VARCHAR(200) NOT NULL,
  address VARCHAR(400),
  city VARCHAR(60),
  state_code VARCHAR(2),
  incorporated_on DATE,
  director_dins VARCHAR(200),
  filed_on DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS RAW_REGISTRY.OWNERSHIP_EDGE (
  holder_cin VARCHAR(24) NOT NULL,
  held_cin VARCHAR(24) NOT NULL,
  stake_pct DECIMAL(7,4) NOT NULL,
  control_flag BOOLEAN NOT NULL,
  effective_from DATE NOT NULL,
  filed_on DATE NOT NULL,
  load_id VARCHAR(32) NOT NULL,
  loaded_at TIMESTAMP NOT NULL
);
