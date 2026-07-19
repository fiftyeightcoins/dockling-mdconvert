# Questions Answerable via RAG on the Knowledge Graph

Grouped by the kind of graph traversal each needs.

## A. Single-node lookup (narrative/fulltext retrieval only)
1. What happened during the 2019 Strait of Hormuz tanker attacks?
2. What sanctions did the US impose on Iran's oil sector in 2018–2019?
3. Describe the JCPOA-related sanctions relief and when it happened.
4. What was Iran's crude oil export volume to China in 2015?
5. Summarize the maximum-pressure sanctions campaign.

## B. Event → market impact (1–2 hop: Event → Day → prices)
6. How much did Brent crude move after Iraq invaded Kuwait in 1990?
7. What was Brent's price on the exact day of a given geopolitical event?
8. Which geopolitical events caused a Brent price shock greater than 20%?
9. What was OPEC production and the US rig count around the 2008 price peak?
10. How long did the market impact of the 2019 tanker attacks last, and what happened to volatility (`brent_30d_volatility_pct`) that month?

## C. Event/Sanction → regional & Hormuz risk
11. Which events threatened the Strait of Hormuz, and how severe were they?
12. What is the historical relationship between Hormuz-threatening events and `hormuz_risk_premium_pct`?
13. Which months had the highest `hormuz_closure_probability_pct`, and what events coincided with them?
14. List all military-action events involving Iran directly.

## D. Sanctions timeline → cumulative pressure
15. How did cumulative sanctions pressure on Iran evolve from 1979 to 2025?
16. Which authority (US, EU, UN) imposed the most sanctions on Iran's financial sector?
17. What sanctions targeted both the oil and financial sectors simultaneously?
18. When was the largest single sanctions-relief action, and what followed it?
19. What was the estimated GDP impact of sanctions imposed during the "maximum pressure" era (2018–2019)?

## E. Export flows → sanctions regime (ExportFlow → UNDER_SANCTION_REGIME → SanctionAction)
20. How did Iran's total oil exports change between 2011 and 2013 (pre- vs. post-EU/US sanctions)?
21. Which sanction was in force during Iran's lowest export year, and what was that export volume?
22. Which destination country kept importing Iranian oil even during heavy-sanctions years?
23. What was Iran's estimated oil revenue in a "heavy" sanctions year vs. a "none" sanctions year?
24. Rank Iran's export destinations by total historical revenue generated.

## F. Cross-domain / multi-hop synthesis (Event ↔ ExportFlow via DURING_SANCTIONS_PERIOD, Day ↔ Month ↔ Year)
25. During years when Iran's exports were under heavy sanctions, which geopolitical events also occurred, and did they compound the price shock?
26. Compare the geopolitical risk index (`gpr_composite_index`) in years of heavy Iran sanctions vs. years without.
27. Is there a correlation between `iran_risk_premium_bps` and Iran's export revenue in the same year?
28. Which years combined (a) a Hormuz-threatening event, (b) heavy sanctions, and (c) a Brent price shock >10%?
29. What was the energy security score (`energy_security_score`) trend before and after major sanctions-relief events (e.g., JCPOA 2015)?
30. Build a timeline correlating sanctions actions, geopolitical events, and Brent price moves for a chosen year range (e.g., 2011–2016).

## G. Aggregation / trend questions (graph-native aggregation via Cypher, not single-node retrieval)
31. What is the average Brent price shock for "extreme" severity events vs. "high" severity events?
32. Which event category (military, sanctions, diplomatic, market, political, economic, terror) has caused the largest average price move?
33. What is the trend in OPEC spare capacity in the 12 months leading up to each extreme-severity event?
34. How many sanctions actions were "relief" vs. "tightening", by decade?
35. Which Authority (US/EU/UN) has been involved in the greatest number of sanctions actions targeting Iran's oil sector specifically?
