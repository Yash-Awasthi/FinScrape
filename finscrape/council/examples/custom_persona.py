"""
Custom persona example for worldfin-council.

Shows how to create a fully custom analyst persona with specific expertise
and integrate it into the council alongside the built-in personas.

Usage:
    python -m finscrape.council.examples.custom_persona
"""
from finscrape.council.council import AgentCouncil
from finscrape.council.base import BaseAgent, AgentVerdict
from finscrape.council.personas import DEFAULT_AGENTS


# ── Create a custom persona ──────────────────────────────────────────────────

class CryptoAnalyst(BaseAgent):
    """
    Specialized agent for cryptocurrency and blockchain analysis.

    This demonstrates how to create a domain-specific persona:
    1. Define name, role, and system_prompt
    2. Set appropriate weight for consensus
    3. The agent receives the same article and produces its own verdict
    """

    def __init__(self, weight: float = 1.0, model: str | None = None):
        super().__init__(weight=weight, model=model)
        # You can add custom state here
        self.specialization = "cryptocurrency"

    @property
    def name(self) -> str:
        return "crypto_analyst"

    @property
    def role(self) -> str:
        return "Cryptocurrency and blockchain specialist"

    @property
    def system_prompt(self) -> str:
        return """\
You are a cryptocurrency and blockchain analyst specializing in:
- DeFi protocol analysis and TVL trends
- Regulatory impact on crypto markets
- Token economics and governance
- Cross-chain interoperability developments
- Institutional adoption signals

Your analysis should consider:
1. How this news affects crypto markets specifically
2. Which tokens/chains are most impacted
3. Regulatory implications for the crypto sector
4. Short-term vs long-term market impact

Return a JSON verdict with:
- verdict: INVEST/OBSERVE/CAUTIOUS/PULL_OUT
- signal_score: -5 to +5 (crypto-specific)
- confidence: 0.0 to 1.0
- reasoning: Your analysis from a crypto perspective
- tickers: Relevant crypto tickers (BTC, ETH, SOL, etc.)
- risk_factors: Crypto-specific risks
- key_insights: Crypto market implications"""


# ── Create another custom persona ────────────────────────────────────────────

class MacroAnalyst(BaseAgent):
    """Macro-economic analyst focusing on interest rates and monetary policy."""

    @property
    def name(self) -> str:
        return "macro"

    @property
    def role(self) -> str:
        return "Macro-economic analyst (rates, bonds, currencies)"

    @property
    def system_prompt(self) -> str:
        return """\
You are a macro-economic analyst focusing on:
- Central bank policy (Fed, ECB, BOJ)
- Interest rate expectations and yield curve
- Currency movements and forex implications
- Bond market signals
- Inflation/deflation dynamics

Analyze how the news affects the macro landscape.
Return a JSON verdict with standard fields."""


# ── Run with mixed personas ──────────────────────────────────────────────────

def main():
    # Combine built-in personas with custom ones
    council = AgentCouncil(
        agents=[
            # Built-in: use first 3 from the default lineup
            *DEFAULT_AGENTS[:3],
            # Custom: crypto specialist
            CryptoAnalyst(weight=1.3),
            # Custom: macro analyst
            MacroAnalyst(weight=1.1),
        ],
        ai_client=mock_ai_client,
        rounds=1,
    )

    verdict = council.deliberate(
        title="SEC approves Bitcoin ETF options trading",
        text=(
            "The SEC has approved options trading on spot Bitcoin ETFs, "
            "expanding institutional access to cryptocurrency derivatives. "
            "This follows the January 2024 spot ETF approvals."
        ),
        metadata={"source": "Bloomberg", "tickers": ["BTC", "ETH"]},
    )

    print("=" * 60)
    print("CUSTOM PERSONA COUNCIL RESULT")
    print("=" * 60)
    print(f"Consensus Score:    {verdict.consensus_score:+.1f}")
    print(f"Consensus Verdict:  {verdict.consensus_verdict}")
    print(f"Confidence:         {verdict.consensus_confidence:.1%}")
    print()
    for v in verdict.individual_verdicts:
        print(f"  [{v.agent_name:14s}] score={v.signal_score:+d} "
              f"verdict={v.verdict}")
    print()
    print("Note: Custom personas receive the same article as built-in")
    print("personas but analyze it from their specific domain perspective.")


def mock_ai_client(prompt: str, system: str, model: str | None = None) -> dict | None:
    """Mock AI client. Replace with real LLM calls in production."""
    import random
    score = random.randint(-3, 4)
    return {
        "verdict": "INVEST" if score >= 3 else "OBSERVE" if score >= 0 else "CAUTIOUS" if score >= -2 else "PULL_OUT",
        "signal_score": score,
        "confidence": round(random.uniform(0.5, 0.9), 2),
        "reasoning": f"Analysis based on the provided article.",
        "tickers": ["BTC", "ETH"],
        "risk_factors": ["Regulatory uncertainty"],
        "key_insights": ["Institutional adoption growing"],
    }


if __name__ == "__main__":
    main()
