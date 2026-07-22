"""
Ingests the oil-geopolitics CSV dataset into Neo4j as a typed knowledge graph,
suited for GraphRAG (unlike raw text chunking).

Design:
  Each row becomes a (:Record {type, date, narrative, embedding, ...raw fields})
  node. `narrative` is a natural-language sentence generated from the row so
  it's meaningful to embed and to show an LLM. `type` is one of:
      event | sanction | export | risk | price_event | price_month

  Graph edges (this is what makes it GraphRAG rather than plain vector RAG):
    (:Record)-[:IN_MONTH]->(:Month {key:"YYYY-MM"})
    (:Record)-[:INVOLVES_COUNTRY]->(:Country {name})

  Because everything anchors to :Month and :Country, at query time we can
  vector-search for the closest Records, then hop through Month/Country to
  pull in *other* records from the same time window or the same country —
  e.g. "what sanctions coincided with this price shock" — which pure
  similarity search would not reliably surface.

Daily oil prices (9,214 rows) are NOT embedded row-by-row (too granular,
mostly redundant). Instead:
  - Only days flagged is_geopolitical_event=1 become price_event Records
  - Every month gets ONE aggregated price_month Record (avg/min/max Brent,
    volatility, return) so trend questions ("what happened to oil prices in
    2012?") are answerable without 9,000 embeddings.

Usage:
    python ingest_csv.py --dir "archive(1) (2)" --provider gemini
"""

import os
import argparse
import glob
import pandas as pd
from dotenv import load_dotenv

from embeddings import get_embedder
from graph_store import Neo4jGraphStore

load_dotenv()


def month_key(date_str) -> str:
    return pd.Timestamp(date_str).strftime("%Y-%m")


# ---------- narrative builders (one per CSV) ----------

def narrative_event(row) -> str:
    return (
        f"On {row['date']}, a {row['severity']}-severity {row['event_type']} event occurred: "
        f"'{row['event_name']}' in {row['region']}. "
        f"Iran involved: {'yes' if row['iran_involved'] else 'no'}. "
        f"Oil price shock: {row['price_shock_pct']}% ({row['shock_direction']}), lasting about "
        f"{row['duration_days']} days. Strait of Hormuz risk flag: {'yes' if row['strait_of_hormuz_risk'] else 'no'}. "
        f"Sanctions-related: {'yes' if row['sanctions_related'] else 'no'}. "
        f"Military action: {'yes' if row['military_action'] else 'no'}."
    )


def narrative_sanction(row) -> str:
    return (
        f"On {row['date']}, {row['imposing_authority']} imposed a {row['sanction_type']} "
        f"({row['category']}) sanction: {row['description']}. "
        f"Estimated GDP impact: {row['estimated_gdp_impact_pct']}%. "
        f"Oil sector affected: {'yes' if row['oil_sector_affected'] else 'no'}; "
        f"financial sector affected: {'yes' if row['financial_sector_affected'] else 'no'}. "
        f"{'This was a sanctions RELIEF action.' if row['is_relief'] else 'This added new sanctions pressure.'} "
        f"Cumulative pressure score at this point: {row['cumulative_pressure_score']}."
    )


def narrative_export(row) -> str:
    return (
        f"In {row['year']}, Iran exported {row['exports_mbd']} million barrels/day of oil to "
        f"{row['destination']}, {row['share_pct']}% of Iran's total exports of "
        f"{row['total_iran_exports_mbd']} mbd that year. Sanctions status: {row['sanctions_status']} "
        f"({'a sanctions year' if row['is_sanctions_year'] else 'not a sanctions year'}). "
        f"Estimated revenue from this: ${row['estimated_revenue_bn_usd']}bn."
    )


def narrative_risk(row) -> str:
    return (
        f"In {row['year']}-{int(row['month']):02d}, the geopolitical risk index stood at "
        f"{row['geopolitical_risk_index']}, Iran-specific risk at {row['iran_specific_risk_bp']} bps, "
        f"VIX at {row['vix_index']}, USD index (DXY) at {row['usd_index_dxy']}, gold at "
        f"${row['gold_usd_oz']}/oz. OPEC spare capacity was {row['opec_spare_capacity_mbd']} mbd, "
        f"Strait of Hormuz closure probability {row['straits_closure_prob_pct']}%, Brent risk premium "
        f"${row['brent_risk_premium_usd']}, energy security index {row['energy_security_index']}."
    )


def narrative_price_event(row) -> str:
    return (
        f"On {row['date']}, a geopolitical event ({row.get('event_type') or 'unspecified'}: "
        f"{row.get('event_description') or 'n/a'}) coincided with Brent at ${row['brent_usd']}, "
        f"WTI at ${row['wti_usd']}, Dubai at ${row['dubai_usd']}. Brent daily return: "
        f"{row['brent_daily_return_pct']}%, 30-day volatility: {row['brent_30d_vol']}, "
        f"Hormuz risk premium: {row['hormuz_risk_premium_pct']}%. OPEC production: "
        f"{row['opec_production_mbd']} mbd, US rig count: {row['us_rig_count']}."
    )


def narrative_price_month(m_key, agg) -> str:
    return (
        f"During {m_key}, Brent crude averaged ${agg['brent_mean']:.2f}/bbl "
        f"(range ${agg['brent_min']:.2f}-${agg['brent_max']:.2f}), WTI averaged ${agg['wti_mean']:.2f}/bbl. "
        f"Average daily return {agg['ret_mean']:.3f}%, average 30-day volatility {agg['vol_mean']:.2f}. "
        f"Average Hormuz risk premium {agg['hormuz_mean']:.2f}%. "
        f"Geopolitical event days this month: {int(agg['event_days'])}."
    )


# ---------- ingestion ----------

def ingest_dataset(data_dir: str, provider: str = None):
    embedder = get_embedder(provider)
    store = Neo4jGraphStore()
    store.create_constraints()
    store.run("CREATE CONSTRAINT month_key IF NOT EXISTS FOR (m:Month) REQUIRE m.key IS UNIQUE")
    store.run("CREATE CONSTRAINT record_id IF NOT EXISTS FOR (r:Record) REQUIRE r.id IS UNIQUE")
    store.run("CREATE CONSTRAINT commodity_name IF NOT EXISTS FOR (c:Commodity) REQUIRE c.name IS UNIQUE")
    store.run("CREATE CONSTRAINT indicator_name IF NOT EXISTS FOR (i:Indicator) REQUIRE i.name IS UNIQUE")
    store.run("CREATE CONSTRAINT org_name IF NOT EXISTS FOR (o:Organization) REQUIRE o.name IS UNIQUE")
    store.run("CREATE CONSTRAINT chokepoint_name IF NOT EXISTS FOR (c:Chokepoint) REQUIRE c.name IS UNIQUE")
    store.create_vector_index(dimension=embedder.dimension, index_name="record_embedding_index")

    records = []  # list of dicts: id, type, date, narrative, month, countries[], extra_props

    # --- geopolitical_events.csv ---
    events = pd.read_csv(os.path.join(data_dir, "geopolitical_events.csv"))
    for i, row in events.iterrows():
        countries = [row["region"]] + (["Iran"] if row["iran_involved"] else [])
        chokepoints = []
        if row.get("strait_of_hormuz_risk") == 1:
            chokepoints.append("Strait of Hormuz")
        records.append({
            "id": f"event_{i}", "type": "event", "date": row["date"],
            "narrative": narrative_event(row), "countries": countries,
            "markets": [], "indicators": [], "organizations": [], "chokepoints": chokepoints,
            "props": {"event_name": row["event_name"], "event_type": row["event_type"],
                      "severity": row["severity"], "price_shock_pct": float(row["price_shock_pct"])},
        })

    # --- sanctions_timeline.csv ---
    sanctions = pd.read_csv(os.path.join(data_dir, "sanctions_timeline.csv"))
    for i, row in sanctions.iterrows():
        records.append({
            "id": f"sanction_{i}", "type": "sanction", "date": row["date"],
            "narrative": narrative_sanction(row), "countries": [row["imposing_authority"], "Iran"],
            "markets": [], "indicators": [], "organizations": [], "chokepoints": [],
            "props": {"sanction_type": row["sanction_type"], "category": row["category"],
                      "is_relief": bool(row["is_relief"])},
        })

    # --- iran_oil_exports.csv ---
    exports = pd.read_csv(os.path.join(data_dir, "iran_oil_exports.csv"))
    for i, row in exports.iterrows():
        records.append({
            "id": f"export_{i}", "type": "export", "date": f"{int(row['year'])}-01-01",
            "narrative": narrative_export(row), "countries": [row["destination"], "Iran"],
            "markets": [], "indicators": [], "organizations": [], "chokepoints": [],
            "props": {"year": int(row["year"]), "destination": row["destination"],
                      "exports_mbd": float(row["exports_mbd"])},
        })

    # --- risk_indicators.csv ---
    risk = pd.read_csv(os.path.join(data_dir, "risk_indicators.csv"))
    for i, row in risk.iterrows():
        markets = []
        indicators = []
        chokepoints = []
        props = {}
        if pd.notna(row.get("gold_usd_oz")): markets.append("Gold")
        if pd.notna(row.get("brent_risk_premium_usd")): markets.append("Brent")
        if pd.notna(row.get("vix_index")): 
            indicators.append("VIX")
            props["vix_index"] = float(row["vix_index"])
        if pd.notna(row.get("usd_index_dxy")): 
            indicators.append("DXY")
            props["usd_index_dxy"] = float(row["usd_index_dxy"])
        if pd.notna(row.get("geopolitical_risk_index")):
            indicators.append("GPR Index")
            props["geopolitical_risk_index"] = float(row["geopolitical_risk_index"])
        if pd.notna(row.get("straits_closure_prob_pct")):
            chokepoints.append("Strait of Hormuz")
            props["straits_closure_prob_pct"] = float(row["straits_closure_prob_pct"])
        records.append({
            "id": f"risk_{i}", "type": "risk", "date": row["date"],
            "narrative": narrative_risk(row), "countries": ["Iran"],
            "markets": markets, "indicators": indicators, "organizations": [], "chokepoints": chokepoints,
            "props": props,
        })

    # --- oil_prices_daily.csv: event days + monthly aggregates ---
    prices = pd.read_csv(os.path.join(data_dir, "oil_prices_daily.csv"))
    event_days = prices[prices["is_geopolitical_event"] == 1]
    for i, row in event_days.iterrows():
        markets = []
        organizations = []
        props = {}
        if pd.notna(row.get("brent_usd")): 
            markets.append("Brent")
            props["brent_usd"] = float(row["brent_usd"])
        if pd.notna(row.get("wti_usd")): 
            markets.append("WTI")
            props["wti_usd"] = float(row["wti_usd"])
        if pd.notna(row.get("dubai_usd")): 
            markets.append("Dubai")
            props["dubai_usd"] = float(row["dubai_usd"])
        if pd.notna(row.get("opec_production_mbd")):
            organizations.append("OPEC")
            props["opec_production_mbd"] = float(row["opec_production_mbd"])
        if pd.notna(row.get("us_rig_count")):
            props["us_rig_count"] = float(row["us_rig_count"])
            
        records.append({
            "id": f"price_event_{i}", "type": "price_event", "date": row["date"],
            "narrative": narrative_price_event(row), "countries": ["Iran"] if "iran" in str(row.get("event_description", "")).lower() else [],
            "markets": markets, "indicators": [], "organizations": organizations, "chokepoints": [],
            "props": props,
        })

    prices["month"] = pd.to_datetime(prices["date"]).dt.strftime("%Y-%m")
    monthly = prices.groupby("month").agg(
        brent_mean=("brent_usd", "mean"), brent_min=("brent_usd", "min"), brent_max=("brent_usd", "max"),
        wti_mean=("wti_usd", "mean"), ret_mean=("brent_daily_return_pct", "mean"),
        vol_mean=("brent_30d_vol", "mean"), hormuz_mean=("hormuz_risk_premium_pct", "mean"),
        event_days=("is_geopolitical_event", "sum"),
    ).reset_index()
    for i, row in monthly.iterrows():
        markets = []
        props = {}
        if pd.notna(row.get("brent_mean")): 
            markets.append("Brent")
            props["brent_mean"] = float(row["brent_mean"])
        if pd.notna(row.get("wti_mean")): 
            markets.append("WTI")
            props["wti_mean"] = float(row["wti_mean"])
            
        records.append({
            "id": f"price_month_{row['month']}", "type": "price_month", "date": f"{row['month']}-01",
            "narrative": narrative_price_month(row["month"], row), "countries": [],
            "markets": markets, "indicators": [], "organizations": [], "chokepoints": [],
            "props": props,
        })

    print(f"Prepared {len(records)} records. Embedding narratives in batches...")
    narratives = [r["narrative"] for r in records]
    vectors = embedder.embed_documents(narratives)

    print("Writing to Neo4j...")
    for rec, vec in zip(records, vectors):
        m_key = month_key(rec["date"])
        store.run("""
        MERGE (r:Record {id: $id})
        SET r.type = $type, r.date = $date, r.narrative = $narrative,
            r.embedding = $embedding, r += $props
        WITH r
        MERGE (m:Month {key: $month_key})
        MERGE (r)-[:IN_MONTH]->(m)
        """, id=rec["id"], type=rec["type"], date=str(rec["date"]),
             narrative=rec["narrative"], embedding=vec, props=rec["props"], month_key=m_key)

        for country in set(c for c in rec["countries"] if c and str(c) != "nan"):
            store.run("""
            MERGE (c:Country {name: $country})
            WITH c
            MATCH (r:Record {id: $id})
            MERGE (r)-[:INVOLVES_COUNTRY]->(c)
            """, country=country, id=rec["id"])

        for market in set(m for m in rec.get("markets", []) if m):
            store.run("""
            MERGE (m:Commodity {name: $market})
            WITH m
            MATCH (r:Record {id: $id})
            MERGE (r)-[:PRICES_COMMODITY]->(m)
            """, market=market, id=rec["id"])

        for ind in set(i for i in rec.get("indicators", []) if i):
            store.run("""
            MERGE (i:Indicator {name: $ind})
            WITH i
            MATCH (r:Record {id: $id})
            MERGE (r)-[:TRACKS_INDICATOR]->(i)
            """, ind=ind, id=rec["id"])
            
        for org in set(o for o in rec.get("organizations", []) if o):
            store.run("""
            MERGE (o:Organization {name: $org})
            WITH o
            MATCH (r:Record {id: $id})
            MERGE (r)-[:INVOLVES_ORGANIZATION]->(o)
            """, org=org, id=rec["id"])
            
        for cp in set(c for c in rec.get("chokepoints", []) if c):
            store.run("""
            MERGE (c:Chokepoint {name: $cp})
            WITH c
            MATCH (r:Record {id: $id})
            MERGE (r)-[:THREATENS_CHOKEPOINT]->(c)
            """, cp=cp, id=rec["id"])

    store.close()
    print(f"Done. Ingested {len(records)} Record nodes with Month/Country graph edges.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Directory containing the CSV files")
    parser.add_argument("--provider", choices=["gemini", "local", "local_docker"], default=None)
    args = parser.parse_args()
    ingest_dataset(args.dir, provider=args.provider)
