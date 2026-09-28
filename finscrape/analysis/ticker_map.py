"""
Company name → ticker symbol mapping for extracting tickers from article text.

The one map. Every caller that turns a company name into a ticker reads this
dict through `resolve_company_tickers`, which reuses the word-boundary match
from `finscrape.entity_map._matches` so a single alnum name like "arm" or
"target" cannot fire on a substring buried in an unrelated word ("pharma",
"price target"). Multi-word phrases still match as substrings, same as
entity_map's own keyword map.

Names are lowercase for case-insensitive matching. Deliberately keeps risky
common-English-word company names ("arm", "target", "block", "meta",
"berkshire", "3m") out as bare keys — those live under their fuller legal
name ("arm holdings", "target corp", ...) so an ordinary sentence never
mints a false ticker.
"""

from __future__ import annotations

from finscrape.entity_map import _matches

# Map of company name fragments (lowercase) → ticker symbol
# Use the shortest unambiguous form of the company name
COMPANY_TO_TICKER: dict[str, str] = {
    # Mega-cap tech
    "apple": "AAPL",
    "microsoft": "MSFT",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "meta platforms": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "broadcom": "AVGO",
    "taiwan semiconductor": "TSM",
    "tsmc": "TSM",
    # Large-cap tech
    "adobe": "ADBE",
    "salesforce": "CRM",
    "netflix": "NFLX",
    "amd": "AMD",
    "advanced micro devices": "AMD",
    "intel": "INTC",
    "qualcomm": "QCOM",
    "cisco": "CSCO",
    "oracle": "ORCL",
    "ibm": "IBM",
    "texas instruments": "TXN",
    "cloudflare": "NET",
    "servicenow": "NOW",
    "intuit": "INTU",
    "uber": "UBER",
    "airbnb": "ABNB",
    "palantir": "PLTR",
    "snowflake": "SNOW",
    "crowdstrike": "CRWD",
    "palo alto networks": "PANW",
    "datadog": "DDOG",
    "shopify": "SHOP",
    "spotify": "SPOT",
    "snap inc": "SNAP",
    "snapchat": "SNAP",
    "pinterest": "PINS",
    "twilio": "TWLO",
    "roku": "ROKU",
    "coinbase": "COIN",
    "robinhood": "HOOD",
    "block inc": "SQ",
    "square": "SQ",
    "paypal": "PYPL",
    "sofi": "SOFI",
    "micron": "MU",
    "arm holdings": "ARM",
    "asml": "ASML",
    "marvell": "MRVL",
    "applied materials": "AMAT",
    "lam research": "LRCX",
    "synopsys": "SNPS",
    "cadence design": "CDNS",
    "dell technologies": "DELL",
    "hewlett packard": "HPE",
    "hp inc": "HPQ",
    # Finance
    "jpmorgan": "JPM",
    "jp morgan": "JPM",
    "bank of america": "BAC",
    "wells fargo": "WFC",
    "goldman sachs": "GS",
    "morgan stanley": "MS",
    "j.p. morgan": "JPM",
    "citigroup": "C",
    "charles schwab": "SCHW",
    "blackrock": "BLK",
    "blackstone": "BX",
    "kkr": "KKR",
    "apollo global": "APO",
    "american express": "AXP",
    "visa inc": "V",
    "mastercard": "MA",
    "berkshire hathaway": "BRK.B",
    # Healthcare / Pharma
    "unitedhealth": "UNH",
    "johnson & johnson": "JNJ",
    "eli lilly": "LLY",
    "novo nordisk": "NVO",
    "abbvie": "ABBV",
    "merck": "MRK",
    "pfizer": "PFE",
    "amgen": "AMGN",
    "gilead": "GILD",
    "moderna": "MRNA",
    "regeneron": "REGN",
    "vertex pharma": "VRTX",
    "biogen": "BIIB",
    "bristol-myers": "BMY",
    "astrazeneca": "AZN",
    "novartis": "NVS",
    "roche": "RHHBY",
    "thermo fisher": "TMO",
    "danaher": "DHR",
    "abbott labs": "ABT",
    "medtronic": "MDT",
    "intuitive surgical": "ISRG",
    "stryker": "SYK",
    "edwards lifesciences": "EW",
    "humana": "HUM",
    "cigna": "CI",
    "cvs health": "CVS",
    # Energy
    "exxon": "XOM",
    "exxonmobil": "XOM",
    "exxon mobil": "XOM",
    "chevron": "CVX",
    "conocophillips": "COP",
    "schlumberger": "SLB",
    "marathon petroleum": "MPC",
    "valero": "VLO",
    "phillips 66": "PSX",
    "pioneer natural": "PXD",
    "occidental": "OXY",
    "devon energy": "DVN",
    "baker hughes": "BKR",
    "halliburton": "HAL",
    "enbridge": "ENB",
    # Consumer / Retail
    "walmart": "WMT",
    "costco": "COST",
    "home depot": "HD",
    "lowe's": "LOW",
    "target corp": "TGT",
    "procter & gamble": "PG",
    "coca-cola": "KO",
    "pepsi": "PEP",
    "pepsico": "PEP",
    "mcdonald's": "MCD",
    "starbucks": "SBUX",
    "nike": "NKE",
    "disney": "DIS",
    "walt disney": "DIS",
    "comcast": "CMCSA",
    "t-mobile": "TMUS",
    "verizon": "VZ",
    "at&t": "T",
    # Industrial / Defense
    "boeing": "BA",
    "lockheed martin": "LMT",
    "raytheon": "RTX",
    "northrop grumman": "NOC",
    "general dynamics": "GD",
    "general electric": "GE",
    "honeywell": "HON",
    "caterpillar": "CAT",
    "deere": "DE",
    "john deere": "DE",
    "3m company": "MMM",
    "union pacific": "UNP",
    "ups": "UPS",
    "fedex": "FDX",
    # Auto
    "ford motor": "F",
    "general motors": "GM",
    "rivian": "RIVN",
    "lucid": "LCID",
    "nio": "NIO",
    "toyota": "TM",
    # Real estate / REITs
    "prologis": "PLD",
    "american tower": "AMT",
    "crown castle": "CCI",
    "equinix": "EQIX",
    "digital realty": "DLR",
    # Other notable
    "accenture": "ACN",
    "automatic data": "ADP",
    "booking holdings": "BKNG",
    "chipotle": "CMG",
    "constellation energy": "CEG",
    "duke energy": "DUK",
    "nexterra": "NEE",
    "nextera energy": "NEE",
    "southern company": "SO",
    "dominion energy": "D",
    "linde": "LIN",
    "air products": "APD",
    "freeport-mcmoran": "FCX",
    "newmont": "NEM",
    "mosaic": "MOS",
    "u.s. steel": "X",
    "us steel": "X",
    "nucor": "NUE",
    "cleveland-cliffs": "CLF",
    # Chinese ADRs
    "alibaba": "BABA",
    "tencent": "TCEHY",
    "baidu": "BIDU",
    "jd.com": "JD",
    "pinduoduo": "PDD",
    "byd": "BYDDY",
    "li auto": "LI",
    "xpeng": "XPEV",
    # Crypto-adjacent
    "microstrategy": "MSTR",
    "marathon digital": "MARA",
    "riot platforms": "RIOT",
}


def resolve_company_tickers(text: str) -> list[str]:
    """Company names present in `text`, resolved to tickers. Sorted, unique."""
    text_lower = (text or "").lower()
    if not text_lower:
        return []
    found = {
        ticker for name, ticker in COMPANY_TO_TICKER.items()
        if _matches(name, text_lower)
    }
    return sorted(found)


# Sector of every ticker above, in the `sectors.TAXONOMY` names. Internet
# platforms (AMZN, GOOGL, META) are technology, as the Laya criteria define it.
_SECTOR_MEMBERS: dict[str, tuple[str, ...]] = {
    "technology": (
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "AVGO", "TSM", "ADBE", "CRM",
        "AMD", "INTC", "QCOM", "CSCO", "ORCL", "IBM", "TXN", "NET", "NOW", "INTU",
        "PLTR", "SNOW", "CRWD", "PANW", "DDOG", "SHOP", "TWLO", "MU", "ARM", "ASML",
        "MRVL", "AMAT", "LRCX", "SNPS", "CDNS", "DELL", "HPE", "HPQ", "ACN", "ADP",
        "BABA", "BIDU", "TCEHY", "JD", "PDD",
    ),
    "communications": ("NFLX", "SPOT", "SNAP", "PINS", "ROKU", "DIS", "CMCSA", "TMUS", "VZ", "T"),
    "financials": (
        "COIN", "HOOD", "SQ", "PYPL", "SOFI", "JPM", "BAC", "WFC", "GS", "MS", "C",
        "SCHW", "BLK", "BX", "KKR", "APO", "AXP", "V", "MA", "BRK.B", "MSTR", "MARA",
        "RIOT",
    ),
    "healthcare": (
        "UNH", "JNJ", "LLY", "NVO", "ABBV", "MRK", "PFE", "AMGN", "GILD", "MRNA",
        "REGN", "VRTX", "BIIB", "BMY", "AZN", "NVS", "RHHBY", "TMO", "DHR", "ABT",
        "MDT", "ISRG", "SYK", "EW", "HUM", "CI", "CVS",
    ),
    "energy": (
        "XOM", "CVX", "COP", "SLB", "MPC", "VLO", "PSX", "PXD", "OXY", "DVN", "BKR",
        "HAL", "ENB",
    ),
    "consumer": (
        "WMT", "COST", "HD", "LOW", "TGT", "PG", "KO", "PEP", "MCD", "SBUX", "NKE",
        "BKNG", "ABNB", "CMG", "TSLA", "F", "GM", "RIVN", "LCID", "NIO", "TM", "BYDDY", "LI",
        "XPEV",
    ),
    "industrials": (
        "BA", "LMT", "RTX", "NOC", "GD", "GE", "HON", "CAT", "DE", "MMM", "UNP", "UPS",
        "FDX", "UBER",
    ),
    "real_estate": ("PLD", "AMT", "CCI", "EQIX", "DLR"),
    "utilities": ("CEG", "DUK", "NEE", "SO", "D"),
    "materials": ("LIN", "APD", "FCX", "NEM", "MOS", "X", "NUE", "CLF"),
}
TICKER_SECTOR: dict[str, str] = {t: s for s, members in _SECTOR_MEMBERS.items() for t in members}
