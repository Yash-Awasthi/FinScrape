"""
Investment Mandate System

Defines investment mandates (constraints, risk limits), validates council
recommendations against mandate rules, manages risk budgeting, and tracks
compliance.  Inspired by ai-hedge-fund's pluggable strategy/pod architecture.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Optional


class RiskTolerance(Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class MandateStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


@dataclass
class MandateRule:
    """A single rule within a mandate."""
    name: str
    description: str
    check: str  # Human-readable check description
    limit: float
    current: float = 0.0

    @property
    def utilization(self) -> float:
        return self.current / self.limit if self.limit > 0 else 0.0

    @property
    def headroom(self) -> float:
        return max(0, self.limit - self.current)

    @property
    def is_breached(self) -> bool:
        return self.current > self.limit


@dataclass
class Position:
    """Current position held under a mandate."""
    ticker: str
    shares: float
    avg_cost: float
    current_price: float
    sector: str = "unknown"

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def pnl(self) -> float:
        return self.shares * (self.current_price - self.avg_cost)

    @property
    def pnl_pct(self) -> float:
        cost = self.shares * self.avg_cost
        return (self.pnl / cost * 100) if cost > 0 else 0.0


@dataclass
class ComplianceViolation:
    """A rule violation detected during compliance check."""
    rule_name: str
    description: str
    limit: float
    actual: float
    severity: str  # "breach", "warning", "info"


@dataclass
class Mandate:
    """
    An investment mandate defining constraints for a strategy or pod.

    Fields mirror ai-hedge-fund's mandate YAML format.
    """
    name: str
    description: str = ""
    risk_tolerance: RiskTolerance = RiskTolerance.MODERATE
    max_position_pct: float = 25.0          # Max % of portfolio in single position
    max_sector_pct: float = 40.0            # Max % of portfolio in single sector
    max_positions: int = 20                 # Max number of positions
    max_drawdown_pct: float = 15.0          # Max drawdown before forced stop
    max_daily_trades: int = 10              # Trade frequency limit
    min_confidence: float = 0.3             # Minimum council confidence to act
    min_score: int = -2                     # Minimum council score to consider
    excluded_sectors: list[str] = field(default_factory=list)
    excluded_tickers: list[str] = field(default_factory=list)
    status: MandateStatus = MandateStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "risk_tolerance": self.risk_tolerance.value,
            "max_position_pct": self.max_position_pct,
            "max_sector_pct": self.max_sector_pct,
            "max_positions": self.max_positions,
            "max_drawdown_pct": self.max_drawdown_pct,
            "min_confidence": self.min_confidence,
            "min_score": self.min_score,
            "excluded_sectors": self.excluded_sectors,
            "excluded_tickers": self.excluded_tickers,
            "status": self.status.value,
        }


# ── Validation ─────────────────────────────────────────────────────────────

def validate_recommendation(
    mandate: Mandate,
    ticker: str,
    sector: str,
    score: int,
    confidence: float,
    current_positions: list[Position],
    portfolio_value: float,
    proposed_value: float,
    daily_trades_today: int = 0,
) -> dict:
    """
    Validate a council recommendation against mandate constraints.

    Returns compliance status and any violations.
    """
    violations: list[ComplianceViolation] = []

    # 1. Score/confidence minimums
    if score < mandate.min_score:
        violations.append(ComplianceViolation(
            rule_name="min_score",
            description=f"Council score {score} below minimum {mandate.min_score}",
            limit=mandate.min_score, actual=score, severity="breach",
        ))
    if confidence < mandate.min_confidence:
        violations.append(ComplianceViolation(
            rule_name="min_confidence",
            description=f"Council confidence {confidence:.2f} below minimum {mandate.min_confidence}",
            limit=mandate.min_confidence, actual=confidence, severity="breach",
        ))

    # 2. Exclusion lists
    if ticker.upper() in [t.upper() for t in mandate.excluded_tickers]:
        violations.append(ComplianceViolation(
            rule_name="excluded_ticker",
            description=f"Ticker {ticker} is on the exclusion list",
            limit=0, actual=1, severity="breach",
        ))
    if sector.lower() in [s.lower() for s in mandate.excluded_sectors]:
        violations.append(ComplianceViolation(
            rule_name="excluded_sector",
            description=f"Sector '{sector}' is on the exclusion list",
            limit=0, actual=1, severity="breach",
        ))

    # 3. Position count
    if len(current_positions) >= mandate.max_positions:
        existing = any(p.ticker.upper() == ticker.upper() for p in current_positions)
        if not existing:
            violations.append(ComplianceViolation(
                rule_name="max_positions",
                description=f"Already at {len(current_positions)} positions (max {mandate.max_positions})",
                limit=mandate.max_positions, actual=len(current_positions), severity="breach",
            ))

    # 4. Position size
    if portfolio_value > 0:
        new_position_value = proposed_value
        position_pct = (new_position_value / portfolio_value) * 100
        # Add existing position if adding to it
        existing_val = sum(p.market_value for p in current_positions if p.ticker.upper() == ticker.upper())
        total_pct = ((existing_val + new_position_value) / portfolio_value) * 100
        if total_pct > mandate.max_position_pct:
            violations.append(ComplianceViolation(
                rule_name="max_position_pct",
                description=f"Position {ticker} would be {total_pct:.1f}% of portfolio (max {mandate.max_position_pct}%)",
                limit=mandate.max_position_pct, actual=total_pct, severity="breach",
            ))
        elif total_pct > mandate.max_position_pct * 0.9:
            violations.append(ComplianceViolation(
                rule_name="max_position_pct_warning",
                description=f"Position {ticker} approaching limit: {total_pct:.1f}% / {mandate.max_position_pct}%",
                limit=mandate.max_position_pct, actual=total_pct, severity="warning",
            ))

    # 5. Sector concentration
    if portfolio_value > 0:
        sector_value = sum(p.market_value for p in current_positions if p.sector.lower() == sector.lower())
        total_sector = (sector_value + proposed_value) / portfolio_value * 100
        if total_sector > mandate.max_sector_pct:
            violations.append(ComplianceViolation(
                rule_name="max_sector_pct",
                description=f"Sector '{sector}' would be {total_sector:.1f}% (max {mandate.max_sector_pct}%)",
                limit=mandate.max_sector_pct, actual=total_sector, severity="breach",
            ))

    # 6. Trade frequency
    if daily_trades_today >= mandate.max_daily_trades:
        violations.append(ComplianceViolation(
            rule_name="max_daily_trades",
            description=f"Already {daily_trades_today} trades today (max {mandate.max_daily_trades})",
            limit=mandate.max_daily_trades, actual=daily_trades_today, severity="breach",
        ))

    breaches = [v for v in violations if v.severity == "breach"]
    return {
        "approved": len(breaches) == 0,
        "violations": [{"rule": v.rule_name, "description": v.description,
                        "severity": v.severity} for v in violations],
        "breach_count": len(breaches),
        "warning_count": len([v for v in violations if v.severity == "warning"]),
    }


# ── Risk Budgeting ─────────────────────────────────────────────────────────

@dataclass
class RiskBudget:
    """Risk allocation across mandates."""
    mandate_name: str
    risk_allocation_pct: float    # % of total risk budget allocated
    risk_used_pct: float = 0.0    # % of allocation used
    var_limit: float = 0.0        # Value at Risk limit (dollar amount)
    var_current: float = 0.0      # Current VaR

    @property
    def risk_remaining(self) -> float:
        return max(0, self.risk_allocation_pct - self.risk_used_pct)

    @property
    def var_remaining(self) -> float:
        return max(0, self.var_limit - self.var_current)


def allocate_risk_budgets(
    mandates: list[Mandate],
    total_risk_budget: float = 100.0,
    portfolio_value: float = 1_000_000.0,
) -> list[RiskBudget]:
    """
    Allocate risk budget across mandates based on risk tolerance.

    Conservative: 15% each, Moderate: 20% each, Aggressive: 25% each.
    Remaining budget is unallocated reserve.
    """
    allocation_pcts = {
        RiskTolerance.CONSERVATIVE: 0.15,
        RiskTolerance.MODERATE: 0.20,
        RiskTolerance.AGGRESSIVE: 0.25,
    }

    budgets = []
    total_allocated = 0.0
    for m in mandates:
        pct = allocation_pcts.get(m.risk_tolerance, 0.20) * total_risk_budget
        var_limit = portfolio_value * (m.max_drawdown_pct / 100)
        budgets.append(RiskBudget(
            mandate_name=m.name,
            risk_allocation_pct=round(pct, 2),
            var_limit=round(var_limit, 2),
        ))
        total_allocated += pct

    return budgets


# ── Compliance Tracking ────────────────────────────────────────────────────

@dataclass
class ComplianceRecord:
    """Record of a compliance check."""
    timestamp: str
    mandate_name: str
    ticker: str
    action: str
    approved: bool
    violations: list[dict]


def track_compliance(
    records: list[ComplianceRecord],
    mandate_name: Optional[str] = None,
) -> dict:
    """
    Aggregate compliance history for reporting.
    """
    filtered = [r for r in records if mandate_name is None or r.mandate_name == mandate_name]
    if not filtered:
        return {"total_checks": 0, "approved": 0, "rejected": 0, "approval_rate": 0.0}

    approved = sum(1 for r in filtered if r.approved)
    rejected = len(filtered) - approved

    # Common violation types
    violation_counts: dict[str, int] = {}
    for r in filtered:
        for v in r.violations:
            name = v.get("rule", "unknown")
            violation_counts[name] = violation_counts.get(name, 0) + 1

    return {
        "total_checks": len(filtered),
        "approved": approved,
        "rejected": rejected,
        "approval_rate": round(approved / len(filtered) * 100, 1) if filtered else 0.0,
        "top_violations": sorted(violation_counts.items(), key=lambda x: -x[1])[:5],
    }
