# Supply chain evaluation: medium

Run 2026-10-26 16:13 · commit cebc854 · chunker v1 · Reader claude-haiku-5-5 (effort medium) · Verifier claude-sonnet-5-5 (effort medium) · 10 filings

## Summary

| | |
|---|---|
| Known relationships | 83 (30 headline) |
| **Found** (right companies, and for unnamed ones the right share and year) | **31** (37% recall) |
| Found with the right share but another year | 0 (recall counting these: 37%) |
| Headline cases found | 14 of 30 |
| Missed | 52 |
| Links in the result | 39 |
| **Wrong links** (match nothing in the truth; to review below) | **6** (precision 85%) |
| Wrong numbers on found links | 0 |
| Ended relationships missed | 0 of 4 |
| Wrongly ended | 0 |
| Links made from a trap sentence | 0 |
| Duplicate unnamed counterparties | 0 extra links in 0 groups |
| Confidence level of the found links | high 31 |
| **Cost** | **US$0.230** (Reader US$0.098, Verifier US$0.131) |
| Tokens | Reader 670,939 in / 62,801 out · Verifier 43,822 in / 4,355 out |

## Recall by kind of case

| Case | Known | Found |
|---|---|---|
| 8k agreement | 2 | 0 |
| china listed | 2 | 0 |
| distributor | 1 | 0 |
| ended | 4 | 1 |
| named customer | 14 | 6 |
| named supplier | 22 | 13 |
| partnership | 3 | 0 |
| private | 19 | 0 |
| risk factor | 7 | 4 |
| unnamed customer | 24 | 10 |
| unnamed supplier | 14 | 1 |

## Candidates and rejections

Candidates by status: linked 47, not_supported 8, partly_supported 3

| Rejected | Count |
|---|---|
| unresolved_company (rule) | 44 |
| not_supported (verifier) | 8 |
| partly_supported_link (verifier) | 3 |
| generic_counterparty (rule) | 2 |
| not_about_filer (rule) | 2 |
| direction_mismatch (rule) | 1 |

## Missed

- **nvda-10k-fy26** Groq → NVIDIA (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **nvda-10k-fy26** NVIDIA → (two direct customers (first)): rejected: generic_counterparty (rule) - 'one of two direct customers' is a group, not one company
- **nvda-10k-fy26** NVIDIA → (two direct customers (second)): rejected: generic_counterparty (rule) - 'one of two direct customers' is a group, not one company
- **nvda-8k-2026-08-17** SB Energy → NVIDIA (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **nvda-8k-2026-08-17** NVIDIA → OpenAI (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** SPIL → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Tongfu Microelectronics → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Tongfu Microelectronics → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Higon (THATIC) → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Sanmina → AMD (headline): rejected: not_supported (verifier) - AMD sold its ZT manufacturing business to Sanmina and Sanmina will be its preferred manufa
- **amd-10k-fy25** AMD → OpenAI (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Ablecom → Super Micro Computer (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Compuware → Super Micro Computer (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Super Micro Computer → Compuware: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Super Micro Computer → Corporate Venture: the Reader did not return it
- **smci-10k-fy26** Corporate Venture → Super Micro Computer (headline): the Reader did not return it
- **smci-10k-fy26** (first of two suppliers) → Super Micro Computer: the Reader did not return it
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: the Reader did not return it
- **smci-10k-fy26** (first of two suppliers) → Super Micro Computer: the Reader did not return it
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (first of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (second of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (third of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (fourth of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (one customer): the Reader did not return it
- **crwv-10k-fy25** CoreWeave → Microsoft (headline): rejected: direction_mismatch (rule) - counterparty_role customer disagrees with who is supplier
- **crwv-10k-fy25** CoreWeave → OpenAI (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **crwv-10k-fy25** NVIDIA → CoreWeave (headline): rejected: not_supported (verifier) - The context says CoreWeave brings NVIDIA GPUs and systems to market first, but never says 
- **crwv-10k-fy25** (largest of three suppliers) → CoreWeave (headline): the Reader did not return it
- **crwv-10k-fy25** (second of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (third of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (largest of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (second of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (third of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (largest of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (second of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (third of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** CoreWeave → (Customer B): the Reader did not return it
- **dell-10k-fy26** Dell → (one customer) (headline): rejected: partly_supported_link (verifier) - Context states one customer accounted for 12% of net revenue in FY2026 with substantially 
- **arm-20f-fy26** Arm → Arm China (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → Arm China: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → Arm China: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → Ampere: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Ampere → Arm: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Linaro → Arm: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → Nuvia (headline): the Reader did not return it
- **arm-20f-fy26** Arm China → Arm (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → (second largest customer): the Reader did not return it
- **arm-20f-fy26** Arm → (third largest customer): the Reader did not return it
- **arm-20f-fy26** Arm → (fourth largest customer): the Reader did not return it
- **arm-20f-fy26** Arm → (second largest customer): the Reader did not return it
- **arm-20f-fy26** Arm → (third largest customer): the Reader did not return it

## Wrong links (6)

These match nothing in the truth. Each needs a look: a wrong link, or a true one the annotation missed (then it goes into the file).

- **smci-10k-fy26** Super Micro Computer, Inc. → Corporate Venture (unnamed customer of Super Micro Computer, Inc., year to 2026-06-30) (supplies, high): We sold products worth $8.1 million, $11.0 million and $21.8 million to the Corporate Venture in the fiscal years 2026, 2025 and 2024, respectively.
- **crwv-10k-fy25** NVIDIA Corporation ↔ CoreWeave, Inc. (partnership, high): For example, in January 2026, we announced that we entered into a collaboration framework with NVIDIA Corporation to expand our long-standing complementary relationship to advance AI adoption at globa
- **crwv-10k-fy25** CoreWeave, Inc. → Customer A (unnamed customer of CoreWeave, Inc., year to 2025-12-31) (supplies · 67% of revenue, high): Customer A | 67 % | 62 % | 35 %
- **dell-10k-fy26** Dell Technologies Inc. → Vmware Llc (supplies, high): Dell Technologies sold and leased products and sold services to VMware.
- **arm-20f-fy26** Arm Holdings plc → an affiliate of SoftBank Group (unnamed customer of Arm Holdings plc, year to 2026-03-31) (supplies, high): For the fiscal years ended March 31, 2026 and 2025, revenue from the licensing and servicing arrangements was $704.4 million and $145.5 million, respectively.
- **arm-20f-fy26** Arm Holdings plc → the single largest customer (unnamed customer of Arm Holdings plc, year to 2026-03-31) (supplies · 16% of revenue, high): For the fiscal year ended March 31, 2026, the Company had three customers that collectively represented 42% of total revenue, with the single largest customer accounting for 16% of total revenue, the 

## Every known relationship

| Filing | Supplier | Customer | Result | Confidence |
|---|---|---|---|---|
| nvda-10k-fy26 | TSMC | NVIDIA | found (headline) | high |
| nvda-10k-fy26 | Samsung | NVIDIA | found | high |
| nvda-10k-fy26 | SK hynix | NVIDIA | found (headline) | high |
| nvda-10k-fy26 | Micron | NVIDIA | found | high |
| nvda-10k-fy26 | Hon Hai | NVIDIA | found | high |
| nvda-10k-fy26 | Wistron | NVIDIA | found | high |
| nvda-10k-fy26 | Fabrinet | NVIDIA | found | high |
| nvda-10k-fy26 | Groq | NVIDIA | missed (headline) |  |
| nvda-10k-fy26 | NVIDIA | (one direct customer) | found (headline) | high |
| nvda-10k-fy26 | NVIDIA | (another direct customer) | found (headline) | high |
| nvda-10k-fy26 | NVIDIA | (one direct customer) | found | high |
| nvda-10k-fy26 | NVIDIA | (two direct customers (first)) | missed |  |
| nvda-10k-fy26 | NVIDIA | (two direct customers (second)) | missed |  |
| nvda-10k-fy26 | NVIDIA | (one direct customer) | found | high |
| nvda-8k-2026-08-17 | SB Energy | NVIDIA | missed (headline) |  |
| nvda-8k-2026-08-17 | NVIDIA | OpenAI | missed (headline) |  |
| amd-10k-fy25 | TSMC | AMD | found (headline) | high |
| amd-10k-fy25 | GlobalFoundries | AMD | found (headline) | high |
| amd-10k-fy25 | UMC | AMD | found | high |
| amd-10k-fy25 | Samsung | AMD | found | high |
| amd-10k-fy25 | SPIL | AMD | missed |  |
| amd-10k-fy25 | King Yuan Electronics | AMD | found | high |
| amd-10k-fy25 | Tongfu Microelectronics | AMD | missed |  |
| amd-10k-fy25 | Tongfu Microelectronics | AMD | missed |  |
| amd-10k-fy25 | Higon (THATIC) | AMD | missed |  |
| amd-10k-fy25 | Sanmina | AMD | missed (headline) |  |
| amd-10k-fy25 | AMD | OpenAI | missed (headline) |  |
| amd-10k-fy25 | AMD | (one Client and Gaming segment customer) | found | high |
| smci-10k-fy26 | Ablecom | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | Compuware | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | Super Micro Computer | Compuware | missed |  |
| smci-10k-fy26 | Leadtek | Super Micro Computer | found (headline) | high |
| smci-10k-fy26 | Super Micro Computer | Leadtek | found | high |
| smci-10k-fy26 | Super Micro Computer | Corporate Venture | missed |  |
| smci-10k-fy26 | Corporate Venture | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | (one supplier) | Super Micro Computer | found (headline) | high |
| smci-10k-fy26 | (first of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (second of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (first of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (second of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | Super Micro Computer | (one customer) | found (headline) | high |
| smci-10k-fy26 | Super Micro Computer | (first of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (second of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (third of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (fourth of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (one customer) | missed |  |
| crwv-10k-fy25 | CoreWeave | Microsoft | missed (headline) |  |
| crwv-10k-fy25 | CoreWeave | OpenAI | missed (headline) |  |
| crwv-10k-fy25 | CoreWeave | Meta | found (headline) | high |
| crwv-10k-fy25 | NVIDIA | CoreWeave | missed (headline) |  |
| crwv-10k-fy25 | (largest of three suppliers) | CoreWeave | missed (headline) |  |
| crwv-10k-fy25 | (second of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (third of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (largest of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (second of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (third of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (largest of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (second of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (third of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | CoreWeave | (Customer B) | found | high |
| crwv-10k-fy25 | CoreWeave | (Customer B) | missed |  |
| crwv-10k-fy25 | CoreWeave | (Customer C) | found | high |
| amkr-10k-fy25 | Amkor | Apple | found (headline) | high |
| amkr-10k-fy25 | Amkor | Qualcomm | found (headline) | high |
| dell-10k-fy26 | VMware | Dell | found (headline) | high |
| dell-10k-fy26 | Dell | (one customer) | missed (headline) |  |
| arm-20f-fy26 | Arm | Arm China | missed (headline) |  |
| arm-20f-fy26 | Arm | Arm China | missed |  |
| arm-20f-fy26 | Arm | Arm China | missed |  |
| arm-20f-fy26 | Arm | Qualcomm | found (headline) | high |
| arm-20f-fy26 | Arm | SoftBank Group | found | high |
| arm-20f-fy26 | Arm | Ampere | missed |  |
| arm-20f-fy26 | Ampere | Arm | missed |  |
| arm-20f-fy26 | Linaro | Arm | missed |  |
| arm-20f-fy26 | Arm | Nuvia | missed (headline) |  |
| arm-20f-fy26 | Arm China | Arm | missed (headline) |  |
| arm-20f-fy26 | Arm | (second largest customer) | found | high |
| arm-20f-fy26 | Arm | (third largest customer) | found | high |
| arm-20f-fy26 | Arm | (second largest customer) | missed |  |
| arm-20f-fy26 | Arm | (third largest customer) | missed |  |
| arm-20f-fy26 | Arm | (fourth largest customer) | missed |  |
| arm-20f-fy26 | Arm | (second largest customer) | missed |  |
| arm-20f-fy26 | Arm | (third largest customer) | missed |  |
