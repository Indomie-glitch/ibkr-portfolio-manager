# Supply chain evaluation: after-341-verifier (run 3 of 3)

Run 2026-10-28 00:19 · commit 57e887d + uncommitted changes · chunker v1 · Reader claude-haiku-5-5 (effort medium) · Verifier claude-sonnet-5-5 (effort medium) · 10 filings

## Summary

| | |
|---|---|
| Known relationships | 90 (30 headline; 7 added to the file after reviewing the first run) |
| **Found** (right companies, and for unnamed ones the right share and year) | **58** (64% recall) |
| Found with the right share but another year | 4 |
| Found, but the number was lost (the customer and passage are right) | 0 (recall counting these two: 69%) |
| Headline cases found | 22 of 30 |
| Missed | 28 |
| Links in the result | 71 |
| **Wrong links** (match nothing in the truth; to review below) | **3** (precision 96%) |
| Wrong numbers on found links | 0 |
| Ended relationships | 1 of 4 found; 1 of those marked ended |
| Wrongly ended | 1 |
| Links made from a trap sentence | 2 |
| Duplicate unnamed counterparties | 0 extra links in 0 groups |
| Confidence level of the found links | medium 62 |
| **Cost** | **US$0.264** (Reader US$0.000, Verifier US$0.264) |
| Tokens | Reader 0 in / 0 out · Verifier 91,995 in / 8,030 out |
| Reader answers | 33 from the cache (they cost US$0.105 when first read), 0 read now; cost read afresh US$0.369 |

## Recall by kind of case

| Case | Known | Found |
|---|---|---|
| 8k agreement | 2 | 1 |
| china listed | 2 | 1 |
| distributor | 1 | 1 |
| ended | 4 | 1 |
| named customer | 17 | 14 |
| named supplier | 24 | 17 |
| partnership | 5 | 1 |
| private | 22 | 11 |
| risk factor | 7 | 5 |
| unnamed customer | 24 | 18 |
| unnamed supplier | 14 | 5 |

## Candidates and rejections

Candidates by status: linked 93, not_supported 8, partly_supported 10

| Rejected | Count |
|---|---|
| partly_supported_link (verifier) | 10 |
| not_supported (verifier) | 8 |
| unresolved_company (rule) | 6 |
| name_not_in_text (rule) | 2 |
| quote_not_found (rule) | 1 |
| direction_mismatch (rule) | 1 |

## Missed

- **nvda-10k-fy26** Groq → NVIDIA (headline): rejected: partly_supported_link (verifier) - The context describes an IP license arrangement between NVIDIA and Groq, which supports th
- **nvda-8k-2026-08-17** NVIDIA → OpenAI (headline): the Reader did not return it
- **amd-10k-fy25** TSMC → AMD (headline): the Reader did not return it
- **amd-10k-fy25** GlobalFoundries → AMD (headline): the Reader did not return it
- **amd-10k-fy25** Tongfu Microelectronics → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Higon (THATIC) → AMD: rejected: partly_supported_link (verifier) - Context says AMD has equity interests in two joint ventures with THATIC, which supports a 
- **amd-10k-fy25** Sanmina → AMD (headline): rejected: partly_supported_link (verifier) - Sanmina is called AMD's preferred partner for manufacturing capabilities, but the context 
- **amd-10k-fy25** AMD → (one Client and Gaming segment customer): the Reader did not return it
- **amd-10k-fy25** AMD → Sony: rejected: partly_supported_link (verifier) - Context says AMD semi-custom SoCs power the Sony PlayStation 5 but does not name Sony Inte
- **smci-10k-fy26** Corporate Venture → Super Micro Computer (headline): the Reader did not return it
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - Context gives 5.1% for the second supplier in fiscal 2025 (components), but the passage li
- **smci-10k-fy26** (first of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - Context gives 5.1% for the second supplier in fiscal 2025 (components), but the passage li
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - Context gives 5.1% for the second supplier in fiscal 2025 (components), but the passage li
- **smci-10k-fy26** Ablecom → Super Micro Computer: rejected: quote_not_found (rule) - the quote isn't in the passage
- **smci-10k-fy26** Compuware → Super Micro Computer: the Reader did not return it
- **crwv-10k-fy25** (largest of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (second of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (third of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (largest of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (second of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** (third of three suppliers) → CoreWeave: the Reader did not return it
- **crwv-10k-fy25** CoreWeave → (Customer B): the Reader did not return it
- **dell-10k-fy26** VMware → Dell: rejected: partly_supported_link (verifier) - Joint marketing, sales and branding arrangements are described, but context does not clear
- **arm-20f-fy26** Arm → Arm China: the Reader did not return it
- **arm-20f-fy26** Arm → Arm China: the Reader did not return it
- **arm-20f-fy26** Ampere → Arm: rejected: not_supported (verifier) - The Ampere Development Agreement was entered by the Company (Arm, per the passage), enabli
- **arm-20f-fy26** Arm → Nuvia (headline): the Reader did not return it
- **arm-20f-fy26** Arm China → Arm (headline): the Reader did not return it

## Found with another year

- **nvda-10k-fy26** NVIDIA → (one direct customer) (known: year to 2025-01-26) was made as `Customer 1 of 3 in the 10-K filed 2026-02-25 (unnamed customer of NVIDIA Corporation, year to 2026-01-25)`
- **nvda-10k-fy26** NVIDIA → (two direct customers (first)) (known: year to 2025-01-26) was made as `Customer 2 of 3 in the 10-K filed 2026-02-25 (unnamed customer of NVIDIA Corporation, year to 2026-01-25)`
- **nvda-10k-fy26** NVIDIA → (two direct customers (second)) (known: year to 2025-01-26) was made as `Customer 3 of 3 in the 10-K filed 2026-02-25 (unnamed customer of NVIDIA Corporation, year to 2026-01-25)`
- **nvda-10k-fy26** NVIDIA → (one direct customer) (known: year to 2024-01-28) was made as `one direct customer in the 10-K filed 2026-02-25 (unnamed customer of NVIDIA Corporation, year to 2026-01-25)`

## Wrong numbers and endings

- **smci-10k-fy26** Super Micro Computer → Corporate Venture: marked ended, the filing says no

## Wrong links (3)

These match nothing in the truth. Each needs a look: a wrong link, or a true one the annotation missed (then it goes into the file).

- **crwv-10k-fy25** CoreWeave, Inc. ↔ third-party infrastructure developer (Kenilworth, New Jersey joint venture partner) in the 10-K filed 2026-03-02 (unnamed customer of CoreWeave, Inc., year to 2025-12-31) (partnership, medium): For example, in June 2025, we entered into a joint venture with a third-party infrastructure developer, to support the acquisition and development of a multi-phase data center campus in Kenilworth, Ne
- **arm-20f-fy26** Arm Holdings plc ↔ Acorn Computers (partnership, medium): Established in 1990, Arm began as a joint venture between Acorn Computers, Apple Computer, and VLSI Technology.
- **arm-20f-fy26** Arm Holdings plc ↔ VLSI Technology (partnership, medium): Established in 1990, Arm began as a joint venture between Acorn Computers, Apple Computer, and VLSI Technology.

## Links made from trap sentences

- **arm-20f-fy26** Arm Holdings plc → Acorn Computers: history: how Arm was founded in 1990, not a current relationship
- **arm-20f-fy26** Arm Holdings plc → VLSI Technology: history: how Arm was founded in 1990, not a current relationship

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
| nvda-10k-fy26 | Groq | NVIDIA | missed (headline) |  |
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
| amd-10k-fy25 | Higon (THATIC) | AMD | missed |  |
| amd-10k-fy25 | Sanmina | AMD | missed (headline) |  |
| amd-10k-fy25 | AMD | OpenAI | found (headline) | medium |
| amd-10k-fy25 | AMD | (one Client and Gaming segment customer) | missed |  |
| amd-10k-fy25 | AMD | Sony | missed |  |
| smci-10k-fy26 | Ablecom | Super Micro Computer | found (headline) | medium |
| smci-10k-fy26 | Compuware | Super Micro Computer | found (headline) | medium |
| smci-10k-fy26 | Super Micro Computer | Compuware | found | medium |
| smci-10k-fy26 | Leadtek | Super Micro Computer | found (headline) | medium |
| smci-10k-fy26 | Super Micro Computer | Leadtek | found | medium |
| smci-10k-fy26 | Super Micro Computer | Corporate Venture | found | medium |
| smci-10k-fy26 | Corporate Venture | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | (one supplier) | Super Micro Computer | found (headline) | medium |
| smci-10k-fy26 | (first of two suppliers) | Super Micro Computer | found | medium |
| smci-10k-fy26 | (second of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (first of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (second of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | Super Micro Computer | (one customer) | found (headline) | medium |
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
| crwv-10k-fy25 | NVIDIA | CoreWeave | found | medium |
| crwv-10k-fy25 | CoreWeave | MagAI Ventures | found | medium |
| amkr-10k-fy25 | Amkor | Apple | found (headline) | medium |
| amkr-10k-fy25 | Amkor | Qualcomm | found (headline) | medium |
| dell-10k-fy26 | VMware | Dell | found (headline) | medium |
| dell-10k-fy26 | Dell | (one customer) | found (headline) | medium |
| dell-10k-fy26 | VMware | Dell | missed |  |
| dell-10k-fy26 | Dell | VMware | found | medium |
| arm-20f-fy26 | Arm | Arm China | found (headline) | medium |
| arm-20f-fy26 | Arm | Arm China | missed |  |
| arm-20f-fy26 | Arm | Arm China | missed |  |
| arm-20f-fy26 | Arm | Qualcomm | found (headline) | medium |
| arm-20f-fy26 | Arm | SoftBank Group | found | medium |
| arm-20f-fy26 | Arm | Ampere | found | medium |
| arm-20f-fy26 | Ampere | Arm | missed |  |
| arm-20f-fy26 | Linaro | Arm | found | medium |
| arm-20f-fy26 | Arm | Nuvia | missed (headline) |  |
| arm-20f-fy26 | Arm China | Arm | missed (headline) |  |
| arm-20f-fy26 | Arm | (second largest customer) | found | medium |
| arm-20f-fy26 | Arm | (third largest customer) | found | medium |
| arm-20f-fy26 | Arm | (second largest customer) | found | medium |
| arm-20f-fy26 | Arm | (third largest customer) | found | medium |
| arm-20f-fy26 | Arm | (fourth largest customer) | found | medium |
| arm-20f-fy26 | Arm | (second largest customer) | found | medium |
| arm-20f-fy26 | Arm | (third largest customer) | found | medium |
