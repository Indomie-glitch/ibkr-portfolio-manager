# Supply chain evaluation: after-341-verifier (run 2 of 3)

Run 2026-10-28 00:19 · commit 096548e + uncommitted changes · chunker v1 · Reader claude-haiku-5-5 (effort medium) · Verifier claude-sonnet-5-5 (effort medium) · 10 filings

## Summary

| | |
|---|---|
| Known relationships | 93 (30 headline; 7 added after reviewing the first runs; file frozen 2026-10-28) |
| **Found** (right companies, and for unnamed ones the right share and year) | **65** (70% recall) |
| Found with the right share but another year | 4 |
| Found, but the number was lost (the customer and passage are right) | 0 (recall counting these two: 74%) |
| Headline cases found | 24 of 30 |
| Missed | 24 |
| Links in the result | 75 |
| **Wrong links** (match nothing in the truth; to review below) | **0** (precision 100%) |
| Wrong numbers on found links | 0 |
| Ended relationships | 2 of 4 found; 2 of those marked ended |
| Wrongly ended | 1 |
| Links made from a trap sentence | 0 |
| Duplicate unnamed counterparties | 0 extra links in 0 groups |
| Confidence level of the found links | medium 69 |
| **Cost** | **US$0.254** (Reader US$0.000, Verifier US$0.254) |
| Tokens | Reader 0 in / 0 out · Verifier 88,863 in / 7,595 out |
| Reader answers | 33 from the cache (they cost US$0.109 when first read), 0 read now; cost read afresh US$0.362 |

## Recall by kind of case

| Case | Known | Found |
|---|---|---|
| 8k agreement | 2 | 1 |
| china listed | 2 | 1 |
| distributor | 1 | 1 |
| ended | 4 | 2 |
| named customer | 17 | 16 |
| named supplier | 24 | 19 |
| partnership | 5 | 2 |
| private | 22 | 15 |
| risk factor | 7 | 5 |
| unnamed customer | 27 | 18 |
| unnamed supplier | 14 | 6 |

## Candidates and rejections

Candidates by status: linked 94, not_supported 5, partly_supported 7

| Rejected | Count |
|---|---|
| unresolved_company (rule) | 9 |
| partly_supported_link (verifier) | 7 |
| not_supported (verifier) | 5 |
| quote_not_found (rule) | 2 |
| name_not_in_text (rule) | 1 |
| not_about_filer (rule) | 1 |
| generic_counterparty (rule) | 1 |

## Missed

- **nvda-8k-2026-08-17** NVIDIA → OpenAI (headline): the Reader did not return it
- **amd-10k-fy25** TSMC → AMD (headline): the Reader did not return it
- **amd-10k-fy25** GlobalFoundries → AMD (headline): the Reader did not return it
- **amd-10k-fy25** Tongfu Microelectronics → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Corporate Venture → Super Micro Computer (headline): the Reader did not return it
- **smci-10k-fy26** (first of two suppliers) → Super Micro Computer: the Reader did not return it
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (one customer) (headline): rejected: partly_supported_link (verifier) - Context says one customer was 28.1% of net sales but describes it as a customer, not a sup
- **smci-10k-fy26** Ablecom → Super Micro Computer: rejected: not_supported (verifier) - Context says they collaborate on design and development with Ablecom, but the claim's part
- **smci-10k-fy26** Compuware → Super Micro Computer: rejected: not_supported (verifier) - Compuware collaboration is design work funded by the company within a contract manufacturi
- **crwv-10k-fy25** (largest of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (second of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (third of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (largest of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (second of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (third of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** CoreWeave → (Customer B): the Reader did not return it
- **crwv-10k-fy25** NVIDIA → CoreWeave: rejected: partly_supported_link (verifier) - The context mentions bringing NVIDIA GPUs to market (GB200, GB300, RTX Pro 6000) but doesn
- **amkr-10k-fy25** Amkor → (one customer (2024)): the Reader did not return it
- **amkr-10k-fy25** Amkor → (one customer (2023)): the Reader did not return it
- **amkr-10k-fy25** Amkor → (a second customer (2024)): the Reader did not return it
- **arm-20f-fy26** Arm → Arm China: the Reader did not return it
- **arm-20f-fy26** Linaro → Arm: rejected: partly_supported_link (verifier) - Linaro is described as a service partner to which Arm pays subscription costs, which fits 
- **arm-20f-fy26** Arm China → Arm (headline): the Reader did not return it

## Found with another year

- **nvda-10k-fy26** NVIDIA → (one direct customer) (known: year to 2025-01-26) was made as `Customer 1 of 3 in the 10-K filed 2026-02-25 (unnamed customer of NVIDIA Corporation, year to 2026-01-25)`
- **nvda-10k-fy26** NVIDIA → (two direct customers (first)) (known: year to 2025-01-26) was made as `Customer 2 of 3 in the 10-K filed 2026-02-25 (unnamed customer of NVIDIA Corporation, year to 2026-01-25)`
- **nvda-10k-fy26** NVIDIA → (two direct customers (second)) (known: year to 2025-01-26) was made as `Customer 3 of 3 in the 10-K filed 2026-02-25 (unnamed customer of NVIDIA Corporation, year to 2026-01-25)`
- **nvda-10k-fy26** NVIDIA → (one direct customer) (known: year to 2024-01-28) was made as `Customer 1 of 1 in the 10-K filed 2026-02-25 (unnamed customer of NVIDIA Corporation, year to 2026-01-25)`

## Wrong numbers and endings

- **smci-10k-fy26** Super Micro Computer → Corporate Venture: marked ended, the filing says no

## Wrong links (0)

These match nothing in the truth. Each needs a look: a wrong link, or a true one the annotation missed. The truth file is frozen, so a true one is listed as possibly missing from truth for a decision, not added to the file.

- none

## Every known relationship

| Filing | Supplier | Customer | Result | Confidence |
|---|---|---|---|---|
| nvda-10k-fy26 | TSMC | NVIDIA | found (headline) | medium |
| nvda-10k-fy26 | Samsung | NVIDIA | found | medium |
| nvda-10k-fy26 | SK hynix | NVIDIA | found (headline) | medium |
| nvda-10k-fy26 | Micron | NVIDIA | found | medium |
| nvda-10k-fy26 | Hon Hai | NVIDIA | found | medium |
| nvda-10k-fy26 | Wistron | NVIDIA | found | medium |
| nvda-10k-fy26 | Fabrinet | NVIDIA | found | medium |
| nvda-10k-fy26 | Groq | NVIDIA | found (headline) | medium |
| nvda-10k-fy26 | NVIDIA | (one direct customer) | found (headline) | medium |
| nvda-10k-fy26 | NVIDIA | (another direct customer) | found (headline) | medium |
| nvda-10k-fy26 | NVIDIA | (one direct customer) | found other year | medium |
| nvda-10k-fy26 | NVIDIA | (two direct customers (first)) | found other year | medium |
| nvda-10k-fy26 | NVIDIA | (two direct customers (second)) | found other year | medium |
| nvda-10k-fy26 | NVIDIA | (one direct customer) | found other year | medium |
| nvda-8k-2026-08-17 | SB Energy | NVIDIA | found (headline) | medium |
| nvda-8k-2026-08-17 | NVIDIA | OpenAI | missed (headline) |  |
| amd-10k-fy25 | TSMC | AMD | missed (headline) |  |
| amd-10k-fy25 | GlobalFoundries | AMD | missed (headline) |  |
| amd-10k-fy25 | UMC | AMD | found | medium |
| amd-10k-fy25 | Samsung | AMD | found | medium |
| amd-10k-fy25 | SPIL | AMD | found | medium |
| amd-10k-fy25 | King Yuan Electronics | AMD | found | medium |
| amd-10k-fy25 | Tongfu Microelectronics | AMD | found | medium |
| amd-10k-fy25 | Tongfu Microelectronics | AMD | missed |  |
| amd-10k-fy25 | Higon (THATIC) | AMD | found | medium |
| amd-10k-fy25 | Sanmina | AMD | found (headline) | medium |
| amd-10k-fy25 | AMD | OpenAI | found (headline) | medium |
| amd-10k-fy25 | AMD | (one Client and Gaming segment customer) | found | medium |
| amd-10k-fy25 | AMD | Sony | found | medium |
| smci-10k-fy26 | Ablecom | Super Micro Computer | found (headline) | medium |
| smci-10k-fy26 | Compuware | Super Micro Computer | found (headline) | medium |
| smci-10k-fy26 | Super Micro Computer | Compuware | found | medium |
| smci-10k-fy26 | Leadtek | Super Micro Computer | found (headline) | medium |
| smci-10k-fy26 | Super Micro Computer | Leadtek | found | medium |
| smci-10k-fy26 | Super Micro Computer | Corporate Venture | found | medium |
| smci-10k-fy26 | Corporate Venture | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | (one supplier) | Super Micro Computer | found (headline) | medium |
| smci-10k-fy26 | (first of two suppliers) | Super Micro Computer | found | medium |
| smci-10k-fy26 | (second of two suppliers) | Super Micro Computer | found | medium |
| smci-10k-fy26 | (first of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (second of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | Super Micro Computer | (one customer) | missed (headline) |  |
| smci-10k-fy26 | Super Micro Computer | (first of four customers) | found | medium |
| smci-10k-fy26 | Super Micro Computer | (second of four customers) | found | medium |
| smci-10k-fy26 | Super Micro Computer | (third of four customers) | found | medium |
| smci-10k-fy26 | Super Micro Computer | (fourth of four customers) | found | medium |
| smci-10k-fy26 | Super Micro Computer | (one customer) | found | medium |
| smci-10k-fy26 | Ablecom | Super Micro Computer | missed |  |
| smci-10k-fy26 | Compuware | Super Micro Computer | missed |  |
| crwv-10k-fy25 | CoreWeave | Microsoft | found (headline) | medium |
| crwv-10k-fy25 | CoreWeave | OpenAI | found (headline) | medium |
| crwv-10k-fy25 | CoreWeave | Meta | found (headline) | medium |
| crwv-10k-fy25 | NVIDIA | CoreWeave | found (headline) | medium |
| crwv-10k-fy25 | (largest of three suppliers) | CoreWeave | found (headline) | medium |
| crwv-10k-fy25 | (second of three suppliers) | CoreWeave | found | medium |
| crwv-10k-fy25 | (third of three suppliers) | CoreWeave | found | medium |
| crwv-10k-fy25 | (largest of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (second of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (third of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (largest of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (second of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | (third of three suppliers) | CoreWeave | missed |  |
| crwv-10k-fy25 | CoreWeave | (Customer B) | found | medium |
| crwv-10k-fy25 | CoreWeave | (Customer B) | missed |  |
| crwv-10k-fy25 | CoreWeave | (Customer C) | found | medium |
| crwv-10k-fy25 | NVIDIA | CoreWeave | missed |  |
| crwv-10k-fy25 | CoreWeave | MagAI Ventures | found | medium |
| amkr-10k-fy25 | Amkor | Apple | found (headline) | medium |
| amkr-10k-fy25 | Amkor | Qualcomm | found (headline) | medium |
| amkr-10k-fy25 | Amkor | (one customer (2024)) | missed |  |
| amkr-10k-fy25 | Amkor | (one customer (2023)) | missed |  |
| amkr-10k-fy25 | Amkor | (a second customer (2024)) | missed |  |
| dell-10k-fy26 | VMware | Dell | found (headline) | medium |
| dell-10k-fy26 | Dell | (one customer) | found (headline) | medium |
| dell-10k-fy26 | VMware | Dell | found | medium |
| dell-10k-fy26 | Dell | VMware | found | medium |
| arm-20f-fy26 | Arm | Arm China | found (headline) | medium |
| arm-20f-fy26 | Arm | Arm China | found | medium |
| arm-20f-fy26 | Arm | Arm China | missed |  |
| arm-20f-fy26 | Arm | Qualcomm | found (headline) | medium |
| arm-20f-fy26 | Arm | SoftBank Group | found | medium |
| arm-20f-fy26 | Arm | Ampere | found | medium |
| arm-20f-fy26 | Ampere | Arm | found | medium |
| arm-20f-fy26 | Linaro | Arm | missed |  |
| arm-20f-fy26 | Arm | Nuvia | found (headline) | medium |
| arm-20f-fy26 | Arm China | Arm | missed (headline) |  |
| arm-20f-fy26 | Arm | (second largest customer) | found | medium |
| arm-20f-fy26 | Arm | (third largest customer) | found | medium |
| arm-20f-fy26 | Arm | (second largest customer) | found | medium |
| arm-20f-fy26 | Arm | (third largest customer) | found | medium |
| arm-20f-fy26 | Arm | (fourth largest customer) | found | medium |
| arm-20f-fy26 | Arm | (second largest customer) | found | medium |
| arm-20f-fy26 | Arm | (third largest customer) | found | medium |
