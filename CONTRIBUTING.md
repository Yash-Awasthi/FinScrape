# Contributing to fin-scrape

AI-powered financial intelligence with 7-agent council system.

## Quick Start

For the current WorldFin API and `web/` dashboard, follow
[Local readiness and setup](docs/LOCAL-READINESS.md). The commands and stack
description below refer to the legacy application; current quality gates are
defined by the root `Makefile` and `.github/workflows/ci.yml`.

```bash
# Clone and setup
git clone https://github.com/Yash-Awasthi/fin-scrape.git
cd fin-scrape
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# Start API server
uvicorn finscrape.api.main:app --reload
```

## Tech Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.10+ |
| Framework | FastAPI | 0.100+ |
| NLP | spaCy | 3.0+ |
| ML | scikit-learn | 1.0+ |
| Testing | pytest | 7.0+ |
| Package | Poetry | 1.0+ |

## Project Structure

```
finscrape/
├── agents/              # Agent implementations
│   ├── council.py       # 7-agent council
│   ├── judge.py         # Council judge
│   └── personas.py      # Agent personas
├── services/            # Business logic
│   ├── content_extractor.py
│   ├── content_scorer.py
│   └── backtesting_engine.py
├── council/             # Standalone council package
│   ├── mandates.py      # Investment mandates
│   ├── backtesting.py   # Backtesting framework
│   └── confidence_scorer.py
└── api/                 # FastAPI endpoints
tests/
├── test_council.py
├── test_services.py
└── test_api.py
```

## Development Guidelines

### Council Agent Development

Agents are the core of fin-scrape:

```python
# finscrape/agents/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class AgentVerdict:
    agent_name: str
    sentiment: float  # -1.0 (bearish) to 1.0 (bullish)
    confidence: float  # 0.0 to 1.0
    reasoning: str
    key_factors: list[str]

class BaseAgent(ABC):
    def __init__(self, name: str, persona: str):
        self.name = name
        self.persona = persona
    
    @abstractmethod
    def analyze(self, data: dict) -> AgentVerdict:
        """Analyze data and return verdict."""
        pass
```

### Service Development

Services are **pure functions** — no database, no async, just analysis:

```python
# Good: Pure function
def score_content(article: dict, criteria: dict) -> float:
    """Score article relevance based on criteria."""
    score = 0.0
    for keyword in criteria.get('keywords', []):
        if keyword.lower() in article['text'].lower():
            score += criteria['weight']
    return min(1.0, score)

# Bad: Service with side effects
async def score_and_store(db: Session, article_id: int) -> float:
    article = await db.get(article_id)
    return score_content(article, {})
```

### Financial Accuracy

When implementing financial concepts:

```python
# Use standard financial formulas
def calculate_sharpe_ratio(returns: list[float], risk_free: float = 0.02) -> float:
    """Calculate annualized Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    
    mean_return = sum(returns) / len(returns)
    std_return = (sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
    
    if std_return == 0:
        return 0.0
    
    return (mean_return - risk_free) / std_return
```

### Code Style

```python
# Follow PEP 8 + ruff defaults
# - Line length: 88
# - Quote style: double quotes
# - Import sorting: isort compatible

# Type hints are required
def calculate_var(
    returns: list[float],
    confidence: float = 0.95,
    method: str = 'historical'
) -> float:
    """Calculate Value at Risk."""
    ...

# Docstrings for public functions
def detect_anomalies(
    values: list[float],
    z_threshold: float = 2.0
) -> list[dict]:
    """Detect statistical anomalies using z-score method.
    
    Args:
        values: List of metric values
        z_threshold: Standard deviations for anomaly (default 2.0)
        
    Returns:
        List of anomaly dicts with index, value, z_score
    """
```

### Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_council.py -v

# Run with coverage
python -m pytest tests/ --cov=finscrape --cov-report=html

# Run only unit tests
python -m pytest tests/unit/ -v
```

### Backtesting

When adding backtesting features:

```python
# Use standard metrics
def compute_metrics(returns: list[float], benchmark: list[float] = None) -> dict:
    """Compute performance metrics."""
    return {
        'total_return': calculate_total_return(returns),
        'sharpe_ratio': calculate_sharpe_ratio(returns),
        'max_drawdown': calculate_max_drawdown(returns),
        'win_rate': calculate_win_rate(returns),
        'alpha': calculate_alpha(returns, benchmark) if benchmark else None,
    }
```

## Pull Request Checklist

- [ ] Tests pass (`python -m pytest tests/ -v`)
- [ ] Type hints on all public functions
- [ ] Financial formulas documented
- [ ] No database calls in service functions
- [ ] README updated if new feature

## Commit Messages

```
feat: add confidence scorer for council
fix: correct Sharpe ratio calculation
council: add quant analyst persona
test: add backtesting edge cases
docs: update API documentation
```
