# Supply chain evaluation: baseline (run 1 of 3)

Run 2026-10-27 19:53 · commit 748d2c9 + uncommitted changes · chunker v1 · Reader claude-haiku-5-5 (effort medium) · Verifier claude-sonnet-5-5 (effort medium) · 10 filings

## Summary

| | |
|---|---|
| Known relationships | 86 (30 headline; 3 added to the file after reviewing the first run) |
| **Found** (right companies, and for unnamed ones the right share and year) | **34** (40% recall) |
| Found with the right share but another year | 0 |
| Found, but the number was lost (the customer and passage are right) | 0 (recall counting these two: 40%) |
| Headline cases found | 16 of 30 |
| Missed | 52 |
| Links in the result | 43 |
| **Wrong links** (match nothing in the truth; to review below) | **0** (precision 100%) |
| Wrong numbers on found links | 0 |
| Ended relationships | 1 of 4 found; 1 of those marked ended |
| Wrongly ended | 1 |
| Links made from a trap sentence | 0 |
| Duplicate unnamed counterparties | 0 extra links in 0 groups |
| Confidence level of the found links | high 34 |
| **Cost** | **US$0.246** (Reader US$0.100, Verifier US$0.146) |
| Tokens | Reader 670,939 in / 65,011 out · Verifier 49,238 in / 4,772 out |
| Reader answers | 0 from the cache (they cost US$0.000 when first read), 33 read now (--fresh); cost read afresh US$0.246 |

## Recall by kind of case

| Case | Known | Found |
|---|---|---|
| 8k agreement | 2 | 1 |
| china listed | 2 | 0 |
| distributor | 1 | 0 |
| ended | 4 | 1 |
| named customer | 15 | 8 |
| named supplier | 22 | 14 |
| partnership | 5 | 1 |
| private | 19 | 2 |
| risk factor | 7 | 5 |
| unnamed customer | 24 | 9 |
| unnamed supplier | 14 | 0 |

## Candidates and rejections

Candidates by status: linked 58, not_supported 4, partly_supported 2

| Rejected | Count |
|---|---|
| unresolved_company (rule) | 39 |
| not_supported (verifier) | 4 |
| partly_supported_link (verifier) | 2 |
| name_not_in_text (rule) | 1 |
| direction_mismatch (rule) | 1 |
| not_about_filer (rule) | 1 |
| generic_counterparty (rule) | 1 |

## Missed

- **nvda-10k-fy26** Groq → NVIDIA (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **nvda-10k-fy26** NVIDIA → (two direct customers (first)): the Reader did not return it
- **nvda-10k-fy26** NVIDIA → (two direct customers (second)): the Reader did not return it
- **nvda-8k-2026-08-17** NVIDIA → OpenAI (headline): the Reader did not return it
- **amd-10k-fy25** SPIL → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Tongfu Microelectronics → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Tongfu Microelectronics → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Higon (THATIC) → AMD: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **amd-10k-fy25** Sanmina → AMD (headline): rejected: not_supported (verifier) - AMD sold its manufacturing business to Sanmina, and Sanmina is AMD's preferred manufacturi
- **amd-10k-fy25** AMD → OpenAI (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Ablecom → Super Micro Computer (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Compuware → Super Micro Computer (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Super Micro Computer → Compuware: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **smci-10k-fy26** Corporate Venture → Super Micro Computer (headline): the Reader did not return it
- **smci-10k-fy26** (one supplier) → Super Micro Computer (headline): rejected: partly_supported_link (verifier) - One supplier accounted for 63.1% of total purchases in fiscal 2026, but the passage doesn'
- **smci-10k-fy26** (first of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - One supplier accounted for 63.1% of total purchases in fiscal 2026, but the passage doesn'
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - One supplier accounted for 63.1% of total purchases in fiscal 2026, but the passage doesn'
- **smci-10k-fy26** (first of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - One supplier accounted for 63.1% of total purchases in fiscal 2026, but the passage doesn'
- **smci-10k-fy26** (second of two suppliers) → Super Micro Computer: rejected: partly_supported_link (verifier) - One supplier accounted for 63.1% of total purchases in fiscal 2026, but the passage doesn'
- **smci-10k-fy26** Super Micro Computer → (first of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (second of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (third of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (fourth of four customers): the Reader did not return it
- **smci-10k-fy26** Super Micro Computer → (one customer): the Reader did not return it
- **crwv-10k-fy25** CoreWeave → Microsoft (headline): rejected: direction_mismatch (rule) - counterparty_role customer disagrees with who is supplier
- **crwv-10k-fy25** CoreWeave → OpenAI (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
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
- **crwv-10k-fy25** NVIDIA → CoreWeave: rejected: not_supported (verifier) - The context says CoreWeave deploys NVIDIA GB200/GB300 NVL72 systems but never says NVIDIA 
- **arm-20f-fy26** Arm → Arm China (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → Arm China: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → Arm China: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → Ampere: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Ampere → Arm: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Linaro → Arm: rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → Nuvia (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm China → Arm (headline): rejected: unresolved_company (rule) - no_match: not a known company, an index member or an OpenFIGI equity
- **arm-20f-fy26** Arm → (second largest customer): the Reader did not return it
- **arm-20f-fy26** Arm → (third largest customer): the Reader did not return it
- **arm-20f-fy26** Arm → (fourth largest customer): the Reader did not return it
- **arm-20f-fy26** Arm → (second largest customer): the Reader did not return it
- **arm-20f-fy26** Arm → (third largest customer): the Reader did not return it

## Wrong numbers and endings

- **smci-10k-fy26** Super Micro Computer → Corporate Venture: marked ended, the filing says no

## Wrong links (0)

These match nothing in the truth. Each needs a look: a wrong link, or a true one the annotation missed (then it goes into the file).

- none

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
| smci-10k-fy26 | Super Micro Computer | (one customer) | found (headline) | high |
| smci-10k-fy26 | Super Micro Computer | (first of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (second of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (third of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (fourth of four customers) | missed |  |
| smci-10k-fy26 | Super Micro Computer | (one customer) | missed |  |
| crwv-10k-fy25 | CoreWeave | Microsoft | missed (headline) |  |
| crwv-10k-fy25 | CoreWeave | OpenAI | missed (headline) |  |
| crwv-10k-fy25 | CoreWeave | Meta | found (headline) | high |
| crwv-10k-fy25 | NVIDIA | CoreWeave | found (headline) | high |
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
| crwv-10k-fy25 | NVIDIA | CoreWeave | missed |  |
| amkr-10k-fy25 | Amkor | Apple | found (headline) | high |
| amkr-10k-fy25 | Amkor | Qualcomm | found (headline) | high |
| dell-10k-fy26 | VMware | Dell | found (headline) | high |
| dell-10k-fy26 | Dell | (one customer) | found (headline) | high |
| dell-10k-fy26 | VMware | Dell | found | high |
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
