# Supply chain evaluation: baseline (run 2 of 3)

Run 2026-10-27 19:53 · commit 57e887d + uncommitted changes · chunker v1 · Reader claude-haiku-5-5 (effort medium) · Verifier claude-sonnet-5-5 (effort medium) · 10 filings

## Summary

| | |
|---|---|
| Known relationships | 90 (30 headline; 7 added to the file after reviewing the first run) |
| **Found** (right companies, and for unnamed ones the right share and year) | **32** (36% recall) |
| Found with the right share but another year | 0 |
| Found, but the number was lost (the customer and passage are right) | 0 (recall counting these two: 36%) |
| Headline cases found | 14 of 30 |
| Missed | 58 |
| Links in the result | 35 |
| **Wrong links** (match nothing in the truth; to review below) | **1** (precision 97%) |
| Wrong numbers on found links | 0 |
| Ended relationships | 1 of 4 found; 1 of those marked ended |
| Wrongly ended | 1 |
| Links made from a trap sentence | 1 |
| Duplicate unnamed counterparties | 0 extra links in 0 groups |
| Confidence level of the found links | high 32 |
| **Cost** | **US$0.222** (Reader US$0.095, Verifier US$0.127) |
| Tokens | Reader 670,939 in / 55,729 out · Verifier 42,232 in / 4,249 out |
| Reader answers | 0 from the cache (they cost US$0.000 when first read), 33 read now (--fresh); cost read afresh US$0.222 |

## Recall by kind of case

| Case | Known | Found |
|---|---|---|
| 8k agreement | 2 | 1 |
| china listed | 2 | 0 |
| distributor | 1 | 0 |
| ended | 4 | 1 |
| named customer | 17 | 8 |
| named supplier | 24 | 13 |
| partnership | 5 | 1 |
| private | 22 | 2 |
| risk factor | 7 | 4 |
| unnamed customer | 24 | 8 |
| unnamed supplier | 14 | 0 |

## Candidates and rejections

Candidates by status: linked 42, partly_supported 13

| Rejected | Count |
|---|---|
| unresolved_company (rule) | 35 |
| partly_supported_link (verifier) | 13 |
| generic_counterparty (rule) | 1 |
| name_not_in_text (rule) | 1 |
| direction_mismatch (rule) | 1 |
| not_about_filer (rule) | 1 |

## Missed

- **nvda-10k-fy26** Groq → NVIDIA (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **nvda-10k-fy26** NVIDIA → (two direct customers (first)): rejected: generic_counterparty (rule) - 'two direct customers' is a group, not one company
- **nvda-10k-fy26** NVIDIA → (two direct customers (second)): rejected: generic_counterparty (rule) - 'two direct customers' is a group, not one company
- **nvda-8k-2026-08-17** NVIDIA → OpenAI (headline): the Reader did not return it
- **amd-10k-fy25** SPIL → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Tongfu Microelectronics → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Tongfu Microelectronics → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Higon (THATIC) → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Sanmina → AMD (headline): rejected: partly_supported_link (verifier) - Sanmina is called AMD's preferred partner for manufacturing, but it is not stated to sell 
- **amd-10k-fy25** AMD → OpenAI (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** AMD → Sony: rejected: partly_supported_link (verifier) - The context ties semi-custom SoC success to game consoles for Sony but does not state AMD 
- **smci-10k-fy26** Ablecom → Super Micro Computer (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Compuware → Super Micro Computer (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Super Micro Computer → Compuware: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Corporate Venture → Super Micro Computer (headline): the Reader did not return it
- **smci-10k-fy26** (one supplier) → Super Micro Computer (headline): rejected: partly_supported_link (verifier) - The 63.1% of total purchases in fiscal 2026 is stated for one supplier, but the passage gi
- **smci-10k-fy26** (first of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - The 63.1% of total purchases in fiscal 2026 is stated for one supplier, but the passage gi
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - The 63.1% of total purchases in fiscal 2026 is stated for one supplier, but the passage gi
- **smci-10k-fy26** (first of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - The 63.1% of total purchases in fiscal 2026 is stated for one supplier, but the passage gi
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - The 63.1% of total purchases in fiscal 2026 is stated for one supplier, but the passage gi
- **smci-10k-fy26** Super Micro Computer → (one customer) (headline): rejected: partly_supported_link (verifier) - The 28.1% share of net sales in fiscal 2026 is stated for one customer, but the passage gi
- **smci-10k-fy26** Super Micro Computer → (first of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (second of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (third of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (fourth of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (one customer): the Reader did not return it
- **smci-10k-fy26** Ablecom → Super Micro Computer: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Compuware → Super Micro Computer: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **crwv-10k-fy25** CoreWeave → Microsoft (headline): rejected: direction_mismatch (rule) - counterparty_role customer disagrees with who is supplier
- **crwv-10k-fy25** CoreWeave → OpenAI (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **crwv-10k-fy25** NVIDIA → CoreWeave (headline): rejected: partly_supported_link (verifier) - The context says CoreWeave brought NVIDIA GPUs (GB200, GB300, RTX Pro 6000) to market firs
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
- **crwv-10k-fy25** CoreWeave → (Customer B): the Reader did not return it
- **crwv-10k-fy25** CoreWeave → (Customer C): the Reader did not return it
- **crwv-10k-fy25** CoreWeave → MagAI Ventures: the Reader did not return it
- **dell-10k-fy26** VMware → Dell: the Reader did not return it
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

## Wrong numbers and endings

- **smci-10k-fy26** Super Micro Computer → Corporate Venture: marked ended, the filing says no

## Wrong links (1)

These match nothing in the truth. Each needs a look: a wrong link, or a true one the annotation missed (then it goes into the file).

- **arm-20f-fy26** Arm Holdings plc → Cadence Design Systems, Inc. (supplies, high): on August 26, 2025, the Company completed the sale of its Artisan foundation IP business, consisting of standard cell libraries, memory compilers, and general-purpose I/Os to Cadence Design Systems, I

## Links made from trap sentences

- **arm-20f-fy26** Arm Holdings plc → Cadence Design Systems, Inc.: a divestiture of a business to Cadence, not a supply relationship

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
| nvda-8k-2026-08-17 | SB Energy | NVIDIA | found (headline) | high |
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
| amd-10k-fy25 | AMD | Sony | missed |  |
| smci-10k-fy26 | Ablecom | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | Compuware | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | Super Micro Computer | Compuware | missed |  |
| smci-10k-fy26 | Leadtek | Super Micro Computer | found (headline) | high |
| smci-10k-fy26 | Super Micro Computer | Leadtek | found | high |
| smci-10k-fy26 | Super Micro Computer | Corporate Venture | found | high |
| smci-10k-fy26 | Corporate Venture | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | (one supplier) | Super Micro Computer | missed (headline) |  |
| smci-10k-fy26 | (first of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (second of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (first of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | (second of two suppliers) | Super Micro Computer | missed |  |
| smci-10k-fy26 | Super Micro Computer | (one customer) | missed (headline) |  |
| smci-10k-fy26 | Super Micro Computer | (first of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (second of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (third of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (fourth of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (one customer) | missed |  |
| smci-10k-fy26 | Ablecom | Super Micro Computer | missed |  |
| smci-10k-fy26 | Compuware | Super Micro Computer | missed |  |
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
| crwv-10k-fy25 | CoreWeave | (Customer B) | missed |  |
| crwv-10k-fy25 | CoreWeave | (Customer B) | missed |  |
| crwv-10k-fy25 | CoreWeave | (Customer C) | missed |  |
| crwv-10k-fy25 | NVIDIA | CoreWeave | found | high |
| crwv-10k-fy25 | CoreWeave | MagAI Ventures | missed |  |
| amkr-10k-fy25 | Amkor | Apple | found (headline) | high |
| amkr-10k-fy25 | Amkor | Qualcomm | found (headline) | high |
| dell-10k-fy26 | VMware | Dell | found (headline) | high |
| dell-10k-fy26 | Dell | (one customer) | found (headline) | high |
| dell-10k-fy26 | VMware | Dell | missed |  |
| dell-10k-fy26 | Dell | VMware | found | high |
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
