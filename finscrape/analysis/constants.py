"""
Sentiment & impact lexicons, source credibility weights, magnitude thresholds,
negation patterns, and constants for the validation layer.
"""

# ---------------------------------------------------------------------------
# Ticker stopwords (common English words / financial abbreviations)
# ---------------------------------------------------------------------------

TICKER_STOPWORDS = frozenset({
    # Common English words (uppercase in headlines/text)
    "A", "AN", "AND", "AS", "AT", "BE", "BUT", "BY", "DO", "FOR",
    "IF", "IN", "IS", "IT", "NO", "OF", "ON", "OR", "THE", "TO",
    "ARE", "CAN", "HAS", "HAD", "HAVE", "MAY", "NOT", "WAS", "WERE",
    "WILL", "BEEN", "ALSO", "BOTH", "EVEN", "FROM", "JUST", "LAST", "MANY", "MOST", "MUCH",
    "NEXT", "NOW", "ONE", "OUT", "OVER", "SAID", "SAYS", "SUCH", "SOME", "SAME",
    "THAN", "THAT", "THIS", "TOLD", "TWO", "WITH", "ALL", "WHAT", "WHEN", "WHERE",
    "WHO", "WHY", "HOW", "MORE", "LESS", "ONLY", "VERY", "EACH", "AFTER", "ABOUT",
    "INTO", "BACK", "DOWN", "DOES", "HERE", "LIKE", "MAKE", "MADE",
    "THEM", "THEN", "THEY", "WELL", "WENT", "COME", "COULD",
    "BEING", "BELOW", "ABOVE", "FIRST", "STILL", "WHILE", "WOULD",
    "THEIR", "THESE", "THOSE", "SINCE", "OTHER", "WHICH", "SHOULD", "UNDER", "UNTIL", "EVERY", "AMONG",
    # Headline words
    "NEW", "BIG", "TOP", "KEY", "SET", "HIT", "SAY", "SEE", "GET", "PUT",
    "RUN", "TRY", "END", "OWN", "ADD", "AID", "ASK", "BAD", "BAN", "BET",
    "BIT", "CUT", "DID", "DUE", "FAR", "FEW", "GOT", "HIS", "HER", "ITS",
    "LET", "LOW", "MET", "OLD", "PAY", "PER", "RED", "RAN", "RAW", "WAR",
    "WAY", "WIN", "WON", "YET", "MIX", "NET", "OFF", "OUR",
    # Finance / business terms (not tickers)
    "BANK", "BILL", "BOND", "CASH", "COST", "DATA", "DEAL", "DEBT", "FIRM", "FUND",
    "GAIN", "GOAL", "GOVT", "LOSS", "LAW", "MODEL", "PLAN", "POWER", "RATE", "RISK",
    "ROLE", "SALE", "STOCK", "TEAM", "TECH", "TRADE", "UNIT", "UP", "VALUE", "YEAR",
    "MOVE", "DROP", "RISE", "JUMP", "FALL", "PUSH", "PULL", "HOLD", "PICK", "SHOW",
    "LEAD", "GROW", "LIFT", "NEAR", "HIGH", "FLAT", "CALL", "PART", "HALF",
    "EDGE", "EASE", "FACE", "FILE", "HELP", "KEEP", "LONG", "LOOK", "MARK",
    "OPEN", "PASS", "POST", "SIGN", "STEP", "TAKE", "TEST", "TURN", "VIEW", "VOTE",
    "WORK", "AHEAD", "AMID", "EARLY", "MAJOR", "RALLY", "SHARP", "SHORT",
    "SURGE", "WATCH", "MIXED", "BOOST", "BROAD", "CLOSE", "FOCUS", "FRESH",
    "PRICE", "SHARE", "SHIFT", "SLIDE", "SOLID", "THINK", "TRACK", "WORLD",
    "MARKET", "SECTOR", "INDEX",
    # Financial metrics
    "EPS", "PE", "PB", "ROE", "ROA", "YOY", "QOQ", "MOM", "YTD",
    "TTM", "GAAP", "EBIT", "EBITDA", "FCF", "OCF", "CAPEX", "DPS",
    "NAV", "NIM", "NPL", "FY", "FQ", "IPO", "ETF", "OTC", "DOW", "NYSE", "NASDAQ",
    "CBOE", "FED", "FOMC", "FDIC", "ECB", "IMF", "IRS", "SEC", "GDP", "CPI", "PMI",
    # Executive titles
    "CEO", "CFO", "COO", "CTO", "CMO", "CRO", "EVP", "SVP", "VP",
    # Company suffixes / legal
    "AG", "INC", "LLC", "LP", "LTD", "NV", "PLC", "SA", "AI", "EU", "UK", "UN", "US", "USA", "UAE",
    # Media / source names (attribution noise in text: "CNBC reports", "FT writes")
    "CNBC", "FT", "WSJ", "BBC", "CNN", "MSNBC", "NYT", "REUTERS", "BLOOMBERG",
    "YAHOO", "GOOGLE", "BARRONS", "AP", "AFP", "SKYNEWS",
    # Time zones
    "EST", "EDT", "PST", "PDT", "UTC", "GMT",
    # Misc false positives
    "FREE", "GTA", "VI", "SHRM", "ARR", "ET", "GO",
    "ANY", "FEE", "MAP", "OIL", "GAS", "TAX", "ERA",
    "BREAK", "CHINA", "JAPAN", "INDIA", "KOREA", "TRUMP",
    "BIDEN", "WHITE", "BLACK", "NORTH", "SOUTH", "EAST", "WEST",
    # Agencies, alliances and blocs seen rendering as tradeable chips
    "NATO", "CIA", "FBI", "NSA", "IOM", "WTO", "OPEC", "IAEA", "ICC", "ICJ",
    "UNHCR", "UNSC", "NGO", "OECD", "BRICS", "ASEAN", "G7", "G20", "IDF", "IRGC",
    "EPA", "FAA", "FDA", "DOJ", "DOD", "DHS", "NHS", "RBI", "BOJ", "BOE", "PBOC",
})

# ---------------------------------------------------------------------------
# Sentiment lexicons — expanded with financial jargon & precise phrases
# ---------------------------------------------------------------------------

POSITIVE_STRONG = frozenset({
    # Earnings / results
    "record", "blowout", "blockbuster", "landmark", "historic",
    "unprecedented", "beat expectations", "beat estimates", "smashed",
    "crushes", "soared", "surged", "skyrocketed", "jumped", "rallied",
    "all-time high", "massive deal", "transformative", "profit jumped",
    "revenue grew", "raised guidance", "record revenue", "record profit",
    "exceeded consensus", "blew past estimates", "outperformed",
    # M&A / deals
    "landmark acquisition", "strategic acquisition", "definitive agreement",
    "completed merger", "transformative deal",
    # Upgrades / targets
    "double upgrade", "price target raised significantly",
    # Market / macro
    "rate cut", "stimulus approved", "liquidity injection",
    "market rally", "bull market",
    # Guidance
    "raised outlook", "raised forecast", "upside guidance",
    "above consensus", "upward revision",
})

POSITIVE_WEAK = frozenset({
    "beat", "exceeded", "above", "growth", "gain", "rose", "up",
    "improved", "strong", "positive", "agreed to acquire", "partnership",
    "launched", "increased", "expanded", "upgraded", "raised", "gained",
    "higher", "approved", "secured", "won", "awarded",
    "upgrade", "raised target", "price target raised", "initiated buy",
    "initiated coverage with buy", "reiterated buy", "reaffirmed buy",
    # Additional financial terms
    "beat consensus", "topped estimates", "in-line", "inline",
    "maintained dividend", "increased dividend", "special dividend",
    "buyback", "share repurchase", "authorized repurchase",
    "margin expansion", "margin improvement", "operating leverage",
    "accelerating growth", "organic growth", "comparable sales grew",
    "same-store sales up", "recurring revenue", "backlog increased",
    "order intake", "pipeline growth", "market share gains",
    "debt reduction", "deleveraging", "investment grade",
    "FDA approval", "cleared by regulators", "patent granted",
    "contract awarded", "deal signed", "memorandum of understanding",
    "joint venture", "strategic partnership", "licensing agreement",
    "initiated outperform", "reiterated overweight", "top pick",
})

NEGATIVE_STRONG = frozenset({
    "bankrupt", "bankruptcy", "collapse", "defaulted", "insolvent",
    "catastrophic", "plunged", "crashed", "imploded", "wiped out",
    "fraud", "scandal", "indicted", "missed estimates", "missed expectations",
    "cut guidance", "profit declined", "revenue declined",
    # Additional severe negatives
    "delisted", "trading halted", "margin call", "liquidation",
    "chapter 11", "chapter 7", "ponzi", "embezzlement",
    "criminal charges", "SEC enforcement", "accounting irregularities",
    "restated earnings", "material weakness", "going concern",
    "profit warning", "revenue shortfall", "demand collapse",
    "credit downgrade", "junk rating", "default risk",
    "death cross", "bear market", "flash crash",
    "supply chain collapse", "production halt", "plant shutdown",
    "massive layoffs", "workforce reduction",
})

NEGATIVE_WEAK = frozenset({
    "miss", "missed", "below", "fell", "dropped", "declined", "loss",
    "cut", "layoffs", "laid off", "job cuts", "restructuring", "fine",
    "penalty", "downgraded", "lowered", "warning", "concern", "lawsuit",
    "investigation", "probe", "deficit", "shortfall", "suspended",
    "resignation", "stepped down", "antitrust", "class action",
    "downgrade", "cut target", "price target cut", "initiated sell",
    "initiated underperform", "lowered target", "rating cut",
    # Additional moderate negatives
    "missed consensus", "below expectations", "sequential decline",
    "margin compression", "margin pressure", "cost overruns",
    "write-down", "impairment", "goodwill charge", "inventory buildup",
    "deceleration", "slowing growth", "softening demand",
    "competitive pressure", "market share loss", "pricing pressure",
    "supply disruption", "chip shortage", "raw material costs",
    "regulatory scrutiny", "compliance issues", "consent decree",
    "dividend cut", "dividend suspended", "buyback paused",
    "debt covenant breach", "refinancing risk", "liquidity concerns",
    "guidance withdrawn", "outlook lowered", "cautious outlook",
    "initiated underweight", "reiterated sell", "removed from top picks",
    "insider selling", "lockup expiry",
})

MAGNITUDE_WORDS = frozenset({
    "record", "massive", "major", "huge", "giant", "enormous",
    "landmark", "historic", "unprecedented", "transformative",
    "biggest", "largest", "biggest ever", "largest ever",
    # Additional magnitude terms
    "significant", "substantial", "outsized", "extraordinary",
    "dramatic", "sweeping", "monumental", "seismic",
    "multi-billion", "mega-deal", "mega-merger",
    "once-in-a-generation", "paradigm shift",
})

# ---------------------------------------------------------------------------
# Negation patterns — words/phrases that invert the next sentiment word
# ---------------------------------------------------------------------------

NEGATION_WORDS = frozenset({
    "not", "no", "never", "neither", "nor", "none",
    "don't", "doesn't", "didn't", "won't", "wouldn't",
    "can't", "cannot", "couldn't", "shouldn't", "hasn't",
    "haven't", "hadn't", "isn't", "aren't", "wasn't", "weren't",
    "barely", "hardly", "scarcely", "seldom", "rarely",
    "fail to", "failed to", "fails to", "unable to",
    "lack of", "absence of", "without",
})

# How many words after a negation word to flip sentiment (window size)
NEGATION_WINDOW = 3

# ---------------------------------------------------------------------------
# Source credibility weights (0.0 to 1.0)
# Higher = more credible, used to weight confidence scores
# ---------------------------------------------------------------------------

SOURCE_CREDIBILITY = {
    # Tier 1 — premier financial news
    "bloomberg": 1.0,
    "reuters": 1.0,
    "ft": 0.95,
    "wsj": 0.95,
    "edgar": 0.95,  # SEC filings = primary source
    # Tier 2 — major financial media
    "cnbc": 0.85,
    "marketwatch": 0.80,
    "yahoo": 0.75,
    "investingcom": 0.75,
    "benzinga": 0.70,
    # Tier 3 — analysis / opinion-heavy
    "seekingalpha": 0.60,
    "motleyfool": 0.50,
    # Tier 4 — aggregators / RSS (unknown provenance)
    "rss": 0.50,
    # Default for unknown sources
    "_default": 0.50,
}

# ---------------------------------------------------------------------------
# Recency decay parameters
# Confidence multiplier as a function of article age in hours.
# Uses exponential decay: multiplier = e^(-decay_rate * age_hours)
# ---------------------------------------------------------------------------

RECENCY_DECAY_RATE = 0.05  # half-life ~14 hours
RECENCY_MAX_AGE_HOURS = 48.0  # clamp beyond this

# ---------------------------------------------------------------------------
# Financial magnitude thresholds
# Used for parsing dollar amounts / percentages from article text
# and converting to a magnitude category (low / medium / high)
# ---------------------------------------------------------------------------

MAGNITUDE_THRESHOLDS = {
    "dollar_billions": {
        "high": 10.0,   # $10B+ = high impact
        "medium": 1.0,  # $1B–$10B
        "low": 0.0,     # < $1B
    },
    "dollar_millions": {
        "high": 500.0,   # $500M+ = high impact
        "medium": 50.0,  # $50M–$500M
        "low": 0.0,      # < $50M
    },
    "percentage_beat": {
        "high": 10.0,   # 10%+ beat = high
        "medium": 3.0,  # 3%–10% beat
        "low": 0.0,     # < 3%
    },
    "layoff_count": {
        "high": 10000,   # 10k+ employees
        "medium": 1000,  # 1k–10k
        "low": 0,        # < 1k
    },
    "percentage_move": {
        "high": 5.0,    # 5%+ stock/index move
        "medium": 2.0,  # 2%–5%
        "low": 0.0,     # < 2%
    },
}

# ---------------------------------------------------------------------------
# Event base impact (unchanged, for backward compat)
# ---------------------------------------------------------------------------

EVENT_BASE_IMPACT = {
    "merger_acquisition": 0.90,
    "earnings": 0.80,
    "guidance": 0.70,
    "bankrupt": 0.95,
    "ipo": 0.75,
    "regulatory_decision": 0.70,
    "management_change": 0.60,
    "product_launch": 0.40,
    "market_movement": 0.55,
    "analyst_upgrade": 0.50,
    "analyst_downgrade": 0.50,
    "price_target_change": 0.40,
    "investment_activity": 0.55,
    "geopolitical_event": 0.65,
    "other": 0.30,
}

# ---------------------------------------------------------------------------
# Valid value sets for response validation
# ---------------------------------------------------------------------------

VALID_IMPACT_DIRECTIONS = {"positive", "negative", "mixed", "neutral"}
VALID_MAGNITUDES = {"low", "medium", "high"}
VALID_NOVELTIES = {"breaking", "standard", "follow_up", "rehash"}
VALID_ACTIONABILITIES = {"low", "medium", "high"}
VALID_EVENT_TYPES = {
    "earnings", "guidance", "price_target_change", "analyst_upgrade",
    "analyst_downgrade", "merger_acquisition", "regulatory_decision",
    "product_launch", "management_change", "market_movement",
    "investment_activity", "geopolitical_event", "bankrupt", "ipo", "other",
}
