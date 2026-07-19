# Oil & Iran-Geopolitics Knowledge Graph — Documentation

## 1. Purpose

This knowledge graph (KG) turns five flat CSVs describing oil markets, Iran
sanctions, Iran's crude export flows, and geopolitical events (1990–2025)
into a connected graph that a RAG (Retrieval-Augmented Generation) system
can traverse and reason over — not just full-text search.

Two things were done to make the source data "retrieval-ready":

1. **Column renaming** — every column was renamed from short/ambiguous
   source names (`brent_usd`, `bp`, `date`) to self-describing,
   unit-bearing names (`brent_price_usd_bbl`, `iran_risk_premium_bps`,
   `sanction_date`). This matters for RAG because column/property names
   often get embedded or shown to the LLM directly (e.g. in a Cypher
   result or a node's property listing) — ambiguous names cause the LLM
   to hallucinate meaning, and long correct names improve retrieval
   precision when using vector or fulltext search over property text.
2. **Narrative text fields** — `event_narrative_text`,
   `sanction_narrative_text`, `export_narrative_text` were generated per
   row, converting structured rows into a single natural-language
   sentence. These are the fields you embed for vector search / RAG;
   the structured properties on the same node are used for precise
   Cypher filtering once a hit is found. This "text + structure on the
   same node" pattern is what makes GraphRAG effective — retrieval finds
   the node via language, then the LLM/agent pulls exact numeric facts
   from the node/neighborhood instead of quoting the narrative.

## 2. Source Files → Renamed Files

| Original | Renamed (used for graph load) | Rows |
|---|---|---|
| `geopolitical_events.csv` | `geopolitical_events_kg.csv` | 68 |
| `iran_oil_exports.csv` | `iran_oil_exports_kg.csv` | 360 |
| `oil_prices_daily.csv` | `oil_prices_daily_kg.csv` | 9,214 |
| `risk_indicators.csv` | `risk_indicators_kg.csv` | 424 |
| `sanctions_timeline.csv` | `sanctions_timeline_kg.csv` | 25 |

### 2.1 Column rename map

**geopolitical_events**
| old | new |
|---|---|
| date | event_date |
| event_type | event_category |
| region | event_region |
| iran_involved | involves_iran_flag |
| price_shock_pct | brent_price_shock_pct |
| shock_direction | price_shock_direction |
| duration_days | market_impact_duration_days |
| severity | event_severity_level |
| strait_of_hormuz_risk | threatens_hormuz_flag |
| sanctions_related | is_sanctions_related_flag |
| military_action | is_military_action_flag |
| *(new)* | event_narrative_text |

**iran_oil_exports**
| old | new |
|---|---|
| year | export_year |
| destination | destination_country |
| exports_mbd | exports_to_destination_mbd |
| total_iran_exports_mbd | iran_total_exports_mbd |
| share_pct | destination_share_of_total_pct |
| sanctions_status | sanctions_regime_status |
| is_sanctions_year | is_heavy_sanctions_year_flag |
| estimated_revenue_bn_usd | estimated_export_revenue_bn_usd |
| *(new)* | export_narrative_text |

**oil_prices_daily**
| old | new |
|---|---|
| date | price_date |
| brent_usd | brent_price_usd_bbl |
| wti_usd | wti_price_usd_bbl |
| dubai_usd | dubai_price_usd_bbl |
| brent_wti_spread | brent_wti_spread_usd |
| is_geopolitical_event | has_geopolitical_event_flag |
| event_type | linked_event_category |
| event_description | linked_event_description |
| (others unchanged, unit suffix implicit) |

**risk_indicators**
| old | new |
|---|---|
| date | snapshot_date |
| year | snapshot_year |
| month | snapshot_month |
| geopolitical_risk_index | gpr_composite_index |
| iran_specific_risk_bp | iran_risk_premium_bps |
| vix_index | vix_volatility_index |
| usd_index_dxy | usd_dxy_index |
| gold_usd_oz | gold_price_usd_oz |
| straits_closure_prob_pct | hormuz_closure_probability_pct |
| brent_risk_premium_usd | brent_geopolitical_premium_usd |
| energy_security_index | energy_security_score |

**sanctions_timeline**
| old | new |
|---|---|
| date | sanction_date |
| category | sanction_category |
| description | sanction_description |
| estimated_gdp_impact_pct | iran_gdp_impact_pct |
| oil_sector_affected | targets_oil_sector_flag |
| financial_sector_affected | targets_financial_sector_flag |
| is_relief | is_sanctions_relief_flag |
| cumulative_pressure_score | cumulative_sanctions_pressure_score |
| *(new)* | sanction_narrative_text |

## 3. Graph Schema

### 3.1 Node labels

| Label | Grain | Key property | Notable properties |
|---|---|---|---|
| `Year` | calendar year | `year` | — |
| `Month` | year+month | `monthKey` ("YYYY-MM") | GPR index, VIX, gold, Hormuz closure probability, energy security score (from `risk_indicators`) |
| `Day` | trading date | `date` | Brent/WTI/Dubai prices, returns, volatility, OPEC production, US rig count (from `oil_prices_daily`) |
| `GeopoliticalEvent` | one event | `eventId` | category, severity, price shock %, direction, duration, narrative_text |
| `SanctionAction` | one sanction/relief action | `sanctionId` | type, category, GDP impact, cumulative pressure, narrative_text |
| `ExportFlow` | Iran→destination, per year | `exportId` | exports mbd, share %, revenue, sanctions regime, narrative_text |
| `Country` | nation/bloc | `name` | Iran, US, EU, UN, China, India, Japan, South Korea, Italy, Turkey, Greece, Spain, Syria, Other |
| `Region` | geography | `name` | Middle East, Global |
| `Authority` | sanctioning body | `name` | derived by splitting `imposing_authority` (e.g. "US/EU" → US, EU) |
| `Sector` | economic sector | `name` | Oil, Financial |
| `Strait` | chokepoint | `name` | Strait of Hormuz |

### 3.2 Relationships

| Relationship | From → To | Meaning |
|---|---|---|
| `IN_MONTH` | Day → Month | day belongs to month |
| `IN_YEAR` | Month → Year | month belongs to year |
| `OCCURRED_ON` | GeopoliticalEvent → Day | event date |
| `OCCURRED_IN` | GeopoliticalEvent → Region | event's region |
| `INVOLVES` | GeopoliticalEvent → Country | Iran flagged as direct participant |
| `THREATENS` | GeopoliticalEvent → Strait | event threatens Hormuz shipping |
| `ENACTED_ON` | SanctionAction → Day | date sanction enacted |
| `TARGETS` | SanctionAction → Country | always → Iran |
| `IMPOSED_BY` | SanctionAction → Authority | US / EU / UN (split from combined values) |
| `AFFECTS_SECTOR` | SanctionAction → Sector | Oil and/or Financial |
| `FROM_COUNTRY` | ExportFlow → Country | always → Iran |
| `TO_DESTINATION` | ExportFlow → Country | e.g. China, India |
| `DURING_YEAR` | ExportFlow → Year | year of the flow |
| `UNDER_SANCTION_REGIME` | ExportFlow → SanctionAction | most recent active (non-relief) sanction as of that export year |
| `DURING_SANCTIONS_PERIOD` | GeopoliticalEvent → ExportFlow | event occurred within a heavy-sanctions export year |

### 3.3 Schema diagram (textual)

```
Year ← IN_YEAR ← Month ← IN_MONTH ← Day ← OCCURRED_ON ← GeopoliticalEvent → OCCURRED_IN → Region
                                     ↑                          ↓                    
                                ENACTED_ON                  INVOLVES / THREATENS
                                     ↑                          ↓
                              SanctionAction              Country / Strait
                              ↙        ↘
                        TARGETS      IMPOSED_BY / AFFECTS_SECTOR
                            ↓              ↓
                          Iran      Authority / Sector

ExportFlow → FROM_COUNTRY → Iran
ExportFlow → TO_DESTINATION → Country
ExportFlow → DURING_YEAR → Year
ExportFlow → UNDER_SANCTION_REGIME → SanctionAction
```

## 4. Design Rationale

- **Day/Month/Year as a time backbone** lets any node (event, sanction,
  export, price) roll up or down the calendar hierarchy — this is what
  enables "what else happened that month/year" queries, which are
  central to geopolitical/oil-market RAG.
- **Daily price data kept as node properties on `Day`** (not one node
  per metric) to avoid unnecessary node explosion — 9,214 `Day` nodes is
  cheap; splitting each metric into its own node would multiply that by
  ~10x with no query benefit.
- **`ExportFlow` and `SanctionAction` as first-class nodes** (rather than
  just relationship properties) because both are frequently the *answer*
  to a question ("which sanction caused X") and both carry a
  `narrative_text` field used for embedding/fulltext retrieval.
- **`UNDER_SANCTION_REGIME` and `DURING_SANCTIONS_PERIOD`** are derived
  (computed, not in the source CSVs) relationships that pre-join facts
  that a RAG agent would otherwise need multiple hops/joins to find —
  this is the graph doing "retrieval work" ahead of time.
- **Authorities split on `/`** (e.g. `"US/EU"` → two `IMPOSED_BY` edges)
  so a question like "which sanctions did the EU impose" doesn't require
  string-matching combined authority values.

## 5. Loading Instructions

1. Place the five `*_kg.csv` files in your Neo4j `import/` directory
   (or serve them and swap `file:///` for `https://...` in the script).
2. Run `build_knowledge_graph.cypher` top to bottom in Neo4j Browser or
   `cypher-shell` (Neo4j 5.23+ required for the `CALL (row) { ... }`
   variable-scoped subquery syntax used for batched imports; on older
   versions replace `CALL (row) {` with `CALL { WITH row`).
3. Run the validation queries at the bottom of the script to confirm
   node/relationship counts.

## 6. RAG Retrieval Pattern (recommended)

1. **Vector/fulltext stage**: embed `narrative_text` on
   `GeopoliticalEvent`, `SanctionAction`, `ExportFlow` (a fulltext index
   `narrative_fulltext` is created in the script; a vector index can be
   added the same way if you compute embeddings for these fields).
2. **Graph expansion stage**: once a narrative hit is found, traverse
   1–2 hops (`OCCURRED_ON`→`Day`, `IN_MONTH`→`Month`) to pull in the
   exact numeric context (price on that day, GPR index that month) —
   this grounds the LLM's answer in numbers instead of the fuzzy text.
3. **Answer synthesis**: pass both the narrative and the structured
   neighborhood properties to the LLM as context.
