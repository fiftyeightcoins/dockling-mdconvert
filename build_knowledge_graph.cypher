// =====================================================================
// OIL & GEOPOLITICAL RISK KNOWLEDGE GRAPH — BUILD SCRIPT
// Source: oil_geopolitics dataset (1990–2025), Sergey Nefedov (sergionefedov)
// Target: Neo4j 5.x  (run in Neo4j Browser / cypher-shell)
//
// BEFORE RUNNING:
// 1. Copy the 5 *_kg.csv files into your Neo4j import folder
//    (or host them and use their https:// URL in LOAD CSV).
// 2. Files expected:
//    geopolitical_events_kg.csv, iran_oil_exports_kg.csv,
//    oil_prices_daily_kg.csv, risk_indicators_kg.csv,
//    sanctions_timeline_kg.csv
// =====================================================================


// ---------------------------------------------------------------------
// STEP 0 — CONSTRAINTS & INDEXES  (run once)
// ---------------------------------------------------------------------
CREATE CONSTRAINT year_id IF NOT EXISTS FOR (n:Year) REQUIRE n.year IS UNIQUE;
CREATE CONSTRAINT month_id IF NOT EXISTS FOR (n:Month) REQUIRE n.monthKey IS UNIQUE;
CREATE CONSTRAINT day_id IF NOT EXISTS FOR (n:Day) REQUIRE n.date IS UNIQUE;
CREATE CONSTRAINT country_id IF NOT EXISTS FOR (n:Country) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT region_id IF NOT EXISTS FOR (n:Region) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT authority_id IF NOT EXISTS FOR (n:Authority) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT sector_id IF NOT EXISTS FOR (n:Sector) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT strait_id IF NOT EXISTS FOR (n:Strait) REQUIRE n.name IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:GeopoliticalEvent) REQUIRE n.eventId IS UNIQUE;
CREATE CONSTRAINT sanction_id IF NOT EXISTS FOR (n:SanctionAction) REQUIRE n.sanctionId IS UNIQUE;
CREATE CONSTRAINT export_id IF NOT EXISTS FOR (n:ExportFlow) REQUIRE n.exportId IS UNIQUE;

CREATE INDEX event_date_idx IF NOT EXISTS FOR (n:GeopoliticalEvent) ON (n.event_date);
CREATE INDEX sanction_date_idx IF NOT EXISTS FOR (n:SanctionAction) ON (n.sanction_date);
CREATE INDEX day_flag_idx IF NOT EXISTS FOR (n:Day) ON (n.has_geopolitical_event_flag);
CREATE FULLTEXT INDEX narrative_fulltext IF NOT EXISTS
FOR (n:GeopoliticalEvent|SanctionAction|ExportFlow) ON EACH [n.narrative_text];


// ---------------------------------------------------------------------
// STEP 1 — SEED REFERENCE (dimension) NODES
// ---------------------------------------------------------------------
UNWIND range(1990, 2025) AS y
MERGE (:Year {year: y});

MERGE (:Country {name:"Iran"})
MERGE (:Country {name:"US"})
MERGE (:Country {name:"EU"})
MERGE (:Country {name:"UN"})
MERGE (:Country {name:"China"})
MERGE (:Country {name:"India"})
MERGE (:Country {name:"Japan"})
MERGE (:Country {name:"South Korea"})
MERGE (:Country {name:"Italy"})
MERGE (:Country {name:"Turkey"})
MERGE (:Country {name:"Greece"})
MERGE (:Country {name:"Spain"})
MERGE (:Country {name:"Syria"})
MERGE (:Country {name:"Other"});

MERGE (:Region {name:"Middle East"})
MERGE (:Region {name:"Global"});

MERGE (:Sector {name:"Oil"})
MERGE (:Sector {name:"Financial"});

MERGE (:Strait {name:"Strait of Hormuz"});

// Authorities referenced in sanctions_timeline (split combined authorities e.g. "US/EU")
// handled in STEP 5 via apoc-free string split.


// ---------------------------------------------------------------------
// STEP 2 — DAILY PRICE NODES  (oil_prices_daily_kg.csv)
// One :Day node per trading date, carrying all daily price/vol/supply metrics.
// ---------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM 'file:///oil_prices_daily_kg.csv' AS row
CALL (row) {
  MERGE (d:Day {date: date(row.price_date)})
  SET d.brent_price_usd_bbl      = toFloat(row.brent_price_usd_bbl),
      d.wti_price_usd_bbl        = toFloat(row.wti_price_usd_bbl),
      d.dubai_price_usd_bbl      = toFloat(row.dubai_price_usd_bbl),
      d.brent_wti_spread_usd     = toFloat(row.brent_wti_spread_usd),
      d.brent_daily_return_pct   = toFloat(row.brent_daily_return_pct),
      d.brent_30d_volatility_pct = toFloat(row.brent_30d_volatility_pct),
      d.hormuz_risk_premium_pct  = toFloat(row.hormuz_risk_premium_pct),
      d.has_geopolitical_event_flag = toInteger(row.has_geopolitical_event_flag),
      d.opec_production_mbd      = toFloat(row.opec_production_mbd),
      d.us_active_rig_count      = toInteger(row.us_active_rig_count)

  WITH d, row, date(row.price_date) AS dt
  MERGE (mo:Month {monthKey: toString(dt.year) + '-' + right('0' + toString(dt.month), 2)})
    ON CREATE SET mo.year = dt.year, mo.month = dt.month
  MERGE (yr:Year {year: dt.year})
  MERGE (mo)-[:IN_YEAR]->(yr)
  MERGE (d)-[:IN_MONTH]->(mo)
} IN TRANSACTIONS OF 1000 ROWS;


// ---------------------------------------------------------------------
// STEP 3 — MONTHLY RISK SNAPSHOTS  (risk_indicators_kg.csv)
// ---------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM 'file:///risk_indicators_kg.csv' AS row
CALL (row) {
  MERGE (mo:Month {monthKey: row.snapshot_year + '-' + right('0' + row.snapshot_month, 2)})
    ON CREATE SET mo.year = toInteger(row.snapshot_year), mo.month = toInteger(row.snapshot_month)
  SET mo.gpr_composite_index            = toFloat(row.gpr_composite_index),
      mo.iran_risk_premium_bps          = toFloat(row.iran_risk_premium_bps),
      mo.vix_volatility_index           = toFloat(row.vix_volatility_index),
      mo.usd_dxy_index                  = toFloat(row.usd_dxy_index),
      mo.gold_price_usd_oz              = toFloat(row.gold_price_usd_oz),
      mo.opec_spare_capacity_mbd        = toFloat(row.opec_spare_capacity_mbd),
      mo.hormuz_closure_probability_pct = toFloat(row.hormuz_closure_probability_pct),
      mo.brent_geopolitical_premium_usd = toFloat(row.brent_geopolitical_premium_usd),
      mo.energy_security_score          = toFloat(row.energy_security_score)
  MERGE (yr:Year {year: toInteger(row.snapshot_year)})
  MERGE (mo)-[:IN_YEAR]->(yr)
} IN TRANSACTIONS OF 500 ROWS;


// ---------------------------------------------------------------------
// STEP 4 — GEOPOLITICAL EVENTS  (geopolitical_events_kg.csv)
// ---------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM 'file:///geopolitical_events_kg.csv' AS row
CALL (row) {
  MERGE (e:GeopoliticalEvent {eventId: row.event_date + '::' + row.event_name})
  SET e.event_date                  = date(row.event_date),
      e.event_name                  = row.event_name,
      e.event_category              = row.event_category,
      e.brent_price_shock_pct       = toFloat(row.brent_price_shock_pct),
      e.price_shock_direction       = row.price_shock_direction,
      e.market_impact_duration_days = toInteger(row.market_impact_duration_days),
      e.event_severity_level        = row.event_severity_level,
      e.involves_iran_flag          = toInteger(row.involves_iran_flag),
      e.threatens_hormuz_flag       = toInteger(row.threatens_hormuz_flag),
      e.is_sanctions_related_flag   = toInteger(row.is_sanctions_related_flag),
      e.is_military_action_flag     = toInteger(row.is_military_action_flag),
      e.narrative_text              = row.event_narrative_text

  MERGE (d:Day {date: date(row.event_date)})
  MERGE (e)-[:OCCURRED_ON]->(d)

  MERGE (r:Region {name: row.event_region})
  MERGE (e)-[:OCCURRED_IN]->(r)

  WITH e, row
  WHERE row.involves_iran_flag = '1'
  MERGE (iran:Country {name:"Iran"})
  MERGE (e)-[:INVOLVES]->(iran)
} IN TRANSACTIONS OF 200 ROWS;

// separate pass for hormuz relationship (kept out of WHERE-chained block above for clarity)
LOAD CSV WITH HEADERS FROM 'file:///geopolitical_events_kg.csv' AS row
CALL (row) {
  WITH row WHERE row.threatens_hormuz_flag = '1'
  MATCH (e:GeopoliticalEvent {eventId: row.event_date + '::' + row.event_name})
  MERGE (s:Strait {name:"Strait of Hormuz"})
  MERGE (e)-[:THREATENS]->(s)
} IN TRANSACTIONS OF 200 ROWS;


// ---------------------------------------------------------------------
// STEP 5 — SANCTIONS TIMELINE  (sanctions_timeline_kg.csv)
// ---------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM 'file:///sanctions_timeline_kg.csv' AS row
CALL (row) {
  MERGE (s:SanctionAction {sanctionId: row.sanction_date + '::' + row.sanction_category})
  SET s.sanction_date            = date(row.sanction_date),
      s.sanction_type            = row.sanction_type,
      s.sanction_category        = row.sanction_category,
      s.sanction_description     = row.sanction_description,
      s.iran_gdp_impact_pct      = toFloat(row.iran_gdp_impact_pct),
      s.targets_oil_sector_flag  = toInteger(row.targets_oil_sector_flag),
      s.targets_financial_sector_flag = toInteger(row.targets_financial_sector_flag),
      s.is_sanctions_relief_flag = toInteger(row.is_sanctions_relief_flag),
      s.cumulative_pressure_score = toFloat(row.cumulative_sanctions_pressure_score),
      s.narrative_text           = row.sanction_narrative_text

  MERGE (d:Day {date: date(row.sanction_date)})
  MERGE (s)-[:ENACTED_ON]->(d)

  MERGE (iran:Country {name:"Iran"})
  MERGE (s)-[:TARGETS]->(iran)

  WITH s, row
  UNWIND split(row.imposing_authority, '/') AS auth
  MERGE (a:Authority {name: trim(auth)})
  MERGE (s)-[:IMPOSED_BY]->(a)
} IN TRANSACTIONS OF 100 ROWS;

// sector relationships
LOAD CSV WITH HEADERS FROM 'file:///sanctions_timeline_kg.csv' AS row
CALL (row) {
  WITH row WHERE row.targets_oil_sector_flag = '1'
  MATCH (s:SanctionAction {sanctionId: row.sanction_date + '::' + row.sanction_category})
  MERGE (sec:Sector {name:"Oil"})
  MERGE (s)-[:AFFECTS_SECTOR]->(sec)
} IN TRANSACTIONS OF 100 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///sanctions_timeline_kg.csv' AS row
CALL (row) {
  WITH row WHERE row.targets_financial_sector_flag = '1'
  MATCH (s:SanctionAction {sanctionId: row.sanction_date + '::' + row.sanction_category})
  MERGE (sec:Sector {name:"Financial"})
  MERGE (s)-[:AFFECTS_SECTOR]->(sec)
} IN TRANSACTIONS OF 100 ROWS;


// ---------------------------------------------------------------------
// STEP 6 — IRAN OIL EXPORT FLOWS  (iran_oil_exports_kg.csv)
// ---------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM 'file:///iran_oil_exports_kg.csv' AS row
CALL (row) {
  MERGE (x:ExportFlow {exportId: row.export_year + '::' + row.destination_country})
  SET x.export_year                    = toInteger(row.export_year),
      x.destination_country            = row.destination_country,
      x.exports_to_destination_mbd     = toFloat(row.exports_to_destination_mbd),
      x.iran_total_exports_mbd         = toFloat(row.iran_total_exports_mbd),
      x.destination_share_of_total_pct = toFloat(row.destination_share_of_total_pct),
      x.sanctions_regime_status        = row.sanctions_regime_status,
      x.is_heavy_sanctions_year_flag   = toInteger(row.is_heavy_sanctions_year_flag),
      x.estimated_export_revenue_bn_usd = toFloat(row.estimated_export_revenue_bn_usd),
      x.narrative_text                 = row.export_narrative_text

  MERGE (iran:Country {name:"Iran"})
  MERGE (dest:Country {name: row.destination_country})
  MERGE (x)-[:FROM_COUNTRY]->(iran)
  MERGE (x)-[:TO_DESTINATION]->(dest)

  MERGE (yr:Year {year: toInteger(row.export_year)})
  MERGE (x)-[:DURING_YEAR]->(yr)
} IN TRANSACTIONS OF 200 ROWS;


// ---------------------------------------------------------------------
// STEP 7 — CROSS-LINK: sanctions active in the same year as an export flow
// (captures "which sanctions regime applied to this export year")
// ---------------------------------------------------------------------
MATCH (x:ExportFlow)-[:DURING_YEAR]->(yr:Year)
MATCH (s:SanctionAction)
WHERE s.sanction_date.year <= yr.year
  AND s.is_sanctions_relief_flag = 0
WITH x, yr, s
ORDER BY s.sanction_date DESC
WITH x, yr, collect(s)[0] AS mostRecentSanction
WHERE mostRecentSanction IS NOT NULL
MERGE (x)-[:UNDER_SANCTION_REGIME]->(mostRecentSanction);


// ---------------------------------------------------------------------
// STEP 8 — CROSS-LINK: events that fall within a sanctions-heavy year
// (optional enrichment relationship for richer graph traversal)
// ---------------------------------------------------------------------
MATCH (e:GeopoliticalEvent)-[:OCCURRED_ON]->(d:Day)-[:IN_MONTH]->(:Month)-[:IN_YEAR]->(yr:Year)
MATCH (x:ExportFlow)-[:DURING_YEAR]->(yr)
WHERE x.is_heavy_sanctions_year_flag = 1
MERGE (e)-[:DURING_SANCTIONS_PERIOD]->(x);


// ---------------------------------------------------------------------
// VALIDATION QUERIES (run after load to sanity-check)
// ---------------------------------------------------------------------
// MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC;
// MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC;
