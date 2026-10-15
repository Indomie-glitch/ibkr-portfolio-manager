"""Turn IB's company names (all caps, cut off at 28 characters) into display names."""

# IB stops longName at this many characters, so a name this long was probably cut off
IB_NAME_LIMIT = 28

SMALL_WORDS = {"OF", "AND", "THE", "FOR", "DE", "LA", "DU", "IN", "ON", "AT"}
# Abbreviations that read better in capitals (or a fixed spelling)
FIXED_WORDS = {
    "INC": "Inc", "LTD": "Ltd", "CORP": "Corp", "CO": "Co", "LLC": "LLC", "PLC": "PLC",
    "NV": "NV", "SA": "SA", "AG": "AG", "SE": "SE", "ETF": "ETF", "REIT": "REIT",
    "ADR": "ADR", "NL": "NL", "USA": "USA", "US": "US", "UK": "UK",
}
VOWELS = set("AEIOUY")


def _word(word, symbol, first):
    if word in FIXED_WORDS:
        return FIXED_WORDS[word]
    if not first and word in SMALL_WORDS:
        return word.lower()
    # Keep the ticker, words without vowels and "&" words in capitals: "APA", "CSL", "S&P"
    if word == symbol or not VOWELS & set(word) or "&" in word:
        return word
    # Title-case each part of hyphenated words: "COCA-COLA" -> "Coca-Cola"
    return "-".join(part[:1] + part[1:].lower() for part in word.split("-"))


def display_name(long_name, symbol):
    """Return (name, truncated) for a company name from IB."""
    if not long_name:
        return symbol, False
    truncated = len(long_name) >= IB_NAME_LIMIT
    # IB moves a leading "The" to the end: "COCA-COLA CO/THE" means "The Coca-Cola Co"
    if long_name.endswith("/THE"):
        long_name = "THE " + long_name[: -len("/THE")]
    words = long_name.split()
    name = " ".join(_word(w, symbol.upper(), i == 0) for i, w in enumerate(words))
    return name, truncated
