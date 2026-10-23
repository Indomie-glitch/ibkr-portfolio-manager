"""Competitors of a stock (Milestone 9, #111): companies in the same Yahoo industry within the loaded
index universe (constituents.py: S&P 500, Nasdaq 100, Dow, ASX 20 / 50 / 200), largest first.

Yahoo's industries can be narrow (CBA is "Banks - Diversified", Bendigo and BOQ "Banks - Regional"),
so with fewer than MIN_PEERS competitors the group widens to closely related industries, then to
the sector, and says which level it used. Both markets are searched; market caps are compared in
US dollars. Pure functions: routers/indices.py supplies the stock, the universe and the rates.
"""

MIN_PEERS = 4
LIMIT = 20  # largest companies listed (plus the stock itself and any you own outside them)

# Closely related industries that don't share a name before " - " (those that do, like
# "Banks - Diversified" and "Banks - Regional", are grouped by family_of without being listed).
# Our own grouping of Yahoo's industry names.
FAMILIES = {
    "Insurance Brokers": "Insurance",
    "Semiconductors": "Semiconductors", "Semiconductor Equipment & Materials": "Semiconductors",
    "Gold": "Metals & Mining", "Silver": "Metals & Mining", "Copper": "Metals & Mining",
    "Aluminum": "Metals & Mining", "Steel": "Metals & Mining", "Coking Coal": "Metals & Mining",
    "Other Industrial Metals & Mining": "Metals & Mining", "Other Precious Metals & Mining": "Metals & Mining",
    "Biotechnology": "Drugs & biotech", "Drug Manufacturers - General": "Drugs & biotech",
    "Drug Manufacturers - Specialty & Generic": "Drugs & biotech",
    "Medical Devices": "Medical devices", "Medical Instruments & Supplies": "Medical devices",
    "Healthcare Plans": "Healthcare services", "Medical Care Facilities": "Healthcare services",
    "Asset Management": "Capital markets", "Capital Markets": "Capital markets",
    "Financial Data & Stock Exchanges": "Capital markets",
    "Credit Services": "Credit", "Mortgage Finance": "Credit",
    "Internet Retail": "Retail", "Specialty Retail": "Retail", "Apparel Retail": "Retail",
    "Home Improvement Retail": "Retail", "Department Stores": "Retail",
    "Discount Stores": "Staples retail", "Grocery Stores": "Staples retail",
    "Computer Hardware": "Hardware", "Consumer Electronics": "Hardware", "Communication Equipment": "Hardware",
    "Electronic Components": "Hardware", "Scientific & Technical Instruments": "Hardware",
    "Specialty Industrial Machinery": "Machinery", "Farm & Heavy Construction Machinery": "Machinery",
    "Railroads": "Transport", "Trucking": "Transport", "Integrated Freight & Logistics": "Transport",
    "Airlines": "Transport", "Marine Shipping": "Transport",
    "Restaurants": "Travel & leisure", "Lodging": "Travel & leisure", "Travel Services": "Travel & leisure",
    "Resorts & Casinos": "Travel & leisure", "Gambling": "Travel & leisure", "Leisure": "Travel & leisure",
    "Packaged Foods": "Food", "Confectioners": "Food", "Farm Products": "Food",
    "Entertainment": "Media", "Broadcasting": "Media", "Publishing": "Media",
    "Electronic Gaming & Multimedia": "Media", "Internet Content & Information": "Media",
    "Advertising Agencies": "Media",
    "Building Products & Equipment": "Construction", "Engineering & Construction": "Construction",
    "Residential Construction": "Construction", "Building Materials": "Construction",
    "Specialty Chemicals": "Chemicals", "Chemicals": "Chemicals", "Agricultural Inputs": "Chemicals",
    "Waste Management": "Business services", "Specialty Business Services": "Business services",
    "Consulting Services": "Business services", "Staffing & Employment Services": "Business services",
}


def family_of(industry):
    """The family an industry belongs to: "Banks - Regional" -> "Banks", "Gold" -> "Metals & Mining",
    "Oil & Gas E&P" -> "Oil & Gas", or the industry itself when it has no relatives."""
    if not industry:
        return None
    if industry in FAMILIES:
        return FAMILIES[industry]
    if industry.startswith("Oil & Gas "):
        return "Oil & Gas"
    return industry.split(" - ")[0]


def _key(company):
    return company["market"], company["symbol"]


def find(target, universe, usd_rates, owned, min_peers=MIN_PEERS, limit=LIMIT):
    """The stock's competitor group, largest market cap (in US dollars) first.

    target: the stock (market, symbol, name, sector, industry, market_cap, pe, return_1y).
    universe: constituents.universe(); only companies whose Yahoo profile has been looked up count.
    usd_rates: US dollars per unit of each currency ({"USD": 1, "AUD": 0.65}).
    owned: {(market, symbol): con_id} of the stocks you hold.
    Returns level ("industry", "related" or "sector"), label (the industry, family or sector name),
    industries (those included), peers_total (competitors found, not counting the stock) and
    companies (the largest `limit`, plus the stock itself and any you own, each with its rank).
    """
    others = [c for c in universe if c["profile_at"] and _key(c) != _key(target)]
    levels = [
        ("industry", target["industry"], lambda c: c["industry"] == target["industry"]),
        ("related", family_of(target["industry"]), lambda c: family_of(c["industry"]) == family_of(target["industry"])),
        ("sector", target["sector"], lambda c: c["sector"] == target["sector"]),
    ]
    for level, label, matches in levels:
        peers = [c for c in others if label and matches(c)]
        if len(peers) >= min_peers:
            break  # otherwise the widest level (sector) is used, however few it finds

    group = [{**target, "is_self": True}] + [{**c, "is_self": False} for c in peers]
    for company in group:
        currency = "AUD" if company["market"] == "ASX" else "USD"
        rate = usd_rates.get(currency)
        company["currency"] = currency
        company["market_cap_usd"] = company["market_cap"] * rate if company.get("market_cap") and rate else None
    group.sort(key=lambda c: -(c["market_cap_usd"] or 0))

    companies = []
    for rank, company in enumerate(group, start=1):
        con_id = owned.get(_key(company))
        if rank <= limit or company["is_self"] or con_id is not None:
            companies.append({
                "rank": rank, "symbol": company["symbol"], "name": company.get("name"), "market": company["market"],
                "industry": company.get("industry"), "currency": company["currency"],
                "market_cap": company.get("market_cap"), "market_cap_usd": company["market_cap_usd"],
                "return_1y": company.get("return_1y"), "pe": company.get("pe"),
                "is_self": company["is_self"], "owned": con_id is not None, "owned_con_id": con_id,
            })
    return {
        "level": level,
        "label": label,
        "industries": sorted({c["industry"] for c in group if c.get("industry")}),
        "peers_total": len(group) - 1,
        "companies": companies,
    }
