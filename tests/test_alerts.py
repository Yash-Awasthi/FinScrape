"""Tests for the alert rules engine."""

import pytest
from finscrape.alerts import AlertEngine, AlertRule, Condition, Action


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return AlertEngine()


def _rule(name: str, *conditions: Condition, enabled: bool = True) -> AlertRule:
    return AlertRule(name=name, conditions=list(conditions), enabled=enabled)


def _sample_event(**overrides) -> dict:
    base = {
        "subject": "Apple earnings beat expectations",
        "event_type": "earnings",
        "tickers": ["AAPL"],
        "impact_direction": "positive",
        "signal_score": 3,
        "confidence": 0.85,
        "verdict": "INVEST",
        "sources": ["yahoo", "bloomberg"],
        "sector_impact": "technology",
        "magnitude": "high",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Condition evaluation — each operator
# ---------------------------------------------------------------------------

class TestConditionOperators:

    def test_eq(self):
        c = Condition(field="verdict", operator="eq", value="INVEST")
        assert c.evaluate({"verdict": "INVEST"}) is True
        assert c.evaluate({"verdict": "PULL_OUT"}) is False

    def test_neq(self):
        c = Condition(field="verdict", operator="neq", value="INVEST")
        assert c.evaluate({"verdict": "PULL_OUT"}) is True
        assert c.evaluate({"verdict": "INVEST"}) is False

    def test_gt(self):
        c = Condition(field="signal_score", operator="gt", value=3)
        assert c.evaluate({"signal_score": 4}) is True
        assert c.evaluate({"signal_score": 3}) is False
        assert c.evaluate({"signal_score": 2}) is False

    def test_gte(self):
        c = Condition(field="confidence", operator="gte", value=0.8)
        assert c.evaluate({"confidence": 0.9}) is True
        assert c.evaluate({"confidence": 0.8}) is True
        assert c.evaluate({"confidence": 0.7}) is False

    def test_lt(self):
        c = Condition(field="signal_score", operator="lt", value=0)
        assert c.evaluate({"signal_score": -1}) is True
        assert c.evaluate({"signal_score": 0}) is False

    def test_lte(self):
        c = Condition(field="signal_score", operator="lte", value=-4)
        assert c.evaluate({"signal_score": -5}) is True
        assert c.evaluate({"signal_score": -4}) is True
        assert c.evaluate({"signal_score": -3}) is False

    def test_in_operator(self):
        c = Condition(field="verdict", operator="in", value=["INVEST", "OBSERVE"])
        assert c.evaluate({"verdict": "INVEST"}) is True
        assert c.evaluate({"verdict": "OBSERVE"}) is True
        assert c.evaluate({"verdict": "PULL_OUT"}) is False

    def test_not_in(self):
        c = Condition(field="verdict", operator="not_in", value=["INVEST", "OBSERVE"])
        assert c.evaluate({"verdict": "PULL_OUT"}) is True
        assert c.evaluate({"verdict": "INVEST"}) is False

    def test_contains_list_single(self):
        c = Condition(field="tickers", operator="contains", value="AAPL")
        assert c.evaluate({"tickers": ["AAPL", "MSFT"]}) is True
        assert c.evaluate({"tickers": ["GOOGL"]}) is False

    def test_contains_list_multi(self):
        c = Condition(field="tickers", operator="contains", value=["AAPL", "GOOGL"])
        assert c.evaluate({"tickers": ["AAPL", "MSFT"]}) is True  # AAPL present
        assert c.evaluate({"tickers": ["TSLA"]}) is False

    def test_contains_string_fallback(self):
        c = Condition(field="sector_impact", operator="contains", value="tech")
        assert c.evaluate({"sector_impact": "technology"}) is True
        assert c.evaluate({"sector_impact": "healthcare"}) is False

    def test_missing_field_returns_false(self):
        c = Condition(field="verdict", operator="eq", value="INVEST")
        assert c.evaluate({}) is False

    def test_invalid_field_raises(self):
        with pytest.raises(ValueError, match="Invalid condition field"):
            Condition(field="nonexistent", operator="eq", value="x")

    def test_invalid_operator_raises(self):
        with pytest.raises(ValueError, match="Invalid operator"):
            Condition(field="verdict", operator="like", value="x")


# ---------------------------------------------------------------------------
# Action validation
# ---------------------------------------------------------------------------

class TestAction:

    def test_valid_types(self):
        for t in ("telegram", "dashboard_push", "log", "webhook"):
            a = Action(action_type=t)
            assert a.action_type == t

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid action type"):
            Action(action_type="email")

    def test_roundtrip(self):
        a = Action(action_type="webhook", config={"url": "https://example.com"})
        d = a.to_dict()
        a2 = Action.from_dict(d)
        assert a2.action_type == "webhook"
        assert a2.config["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# AlertRule matching
# ---------------------------------------------------------------------------

class TestAlertRule:

    def test_matches_all_conditions(self):
        rule = AlertRule(
            name="test",
            conditions=[
                Condition(field="verdict", operator="eq", value="INVEST"),
                Condition(field="confidence", operator="gte", value=0.8),
            ],
        )
        assert rule.matches(_sample_event()) is True
        assert rule.matches(_sample_event(confidence=0.5)) is False
        assert rule.matches(_sample_event(verdict="PULL_OUT")) is False

    def test_empty_conditions_never_match(self):
        rule = AlertRule(name="empty", conditions=[])
        assert rule.matches(_sample_event()) is False

    def test_roundtrip(self):
        rule = AlertRule(
            name="test",
            conditions=[Condition(field="verdict", operator="eq", value="INVEST")],
            actions=[Action(action_type="log")],
        )
        d = rule.to_dict()
        rule2 = AlertRule.from_dict(d)
        assert rule2.id == rule.id
        assert rule2.name == rule.name
        assert len(rule2.conditions) == 1
        assert len(rule2.actions) == 1


# ---------------------------------------------------------------------------
# Preset rules
# ---------------------------------------------------------------------------

class TestPresets:

    def test_faang_pullout(self):
        conditions, actions = AlertEngine.preset_faang_pullout()
        rule = AlertRule(name="faang", conditions=conditions, actions=actions)
        # PULL_OUT on AAPL -> match
        assert rule.matches(_sample_event(verdict="PULL_OUT", tickers=["AAPL"])) is True
        # PULL_OUT on non-FAANG -> no match
        assert rule.matches(_sample_event(verdict="PULL_OUT", tickers=["TSLA"])) is False
        # INVEST on AAPL -> no match
        assert rule.matches(_sample_event(verdict="INVEST", tickers=["AAPL"])) is False

    def test_high_confidence_invest(self):
        conditions, actions = AlertEngine.preset_high_confidence_invest()
        rule = AlertRule(name="hci", conditions=conditions, actions=actions)
        assert rule.matches(_sample_event(verdict="INVEST", confidence=0.9)) is True
        assert rule.matches(_sample_event(verdict="INVEST", confidence=0.8)) is True
        assert rule.matches(_sample_event(verdict="INVEST", confidence=0.7)) is False
        assert rule.matches(_sample_event(verdict="OBSERVE", confidence=0.9)) is False

    def test_high_impact(self):
        conditions, actions = AlertEngine.preset_high_impact()
        rule = AlertRule(name="hi", conditions=conditions, actions=actions)
        assert rule.matches(_sample_event(signal_score=5)) is True
        assert rule.matches(_sample_event(signal_score=4)) is True
        assert rule.matches(_sample_event(signal_score=3)) is False

    def test_breaking_news(self):
        conditions, actions = AlertEngine.preset_breaking_news()
        rule = AlertRule(name="bn", conditions=conditions, actions=actions)
        assert rule.matches(_sample_event(event_type="breaking_news")) is True
        assert rule.matches(_sample_event(event_type="earnings")) is False


# ---------------------------------------------------------------------------
# Engine evaluate & execute
# ---------------------------------------------------------------------------

class TestEngineEvaluate:

    def test_evaluate_returns_matching_rules(self):
        engine = AlertEngine([
            _rule("Invest Alert", Condition(field="verdict", operator="eq", value="INVEST")),
            _rule("PullOut Alert", Condition(field="verdict", operator="eq", value="PULL_OUT")),
        ])

        matches = engine.evaluate(_sample_event(verdict="INVEST"))
        assert len(matches) == 1
        assert matches[0][0].name == "Invest Alert"

    def test_evaluate_multiple_matches(self):
        engine = AlertEngine([
            _rule("Invest", Condition(field="verdict", operator="eq", value="INVEST")),
            _rule("High Conf", Condition(field="confidence", operator="gte", value=0.8)),
        ])

        matches = engine.evaluate(_sample_event(verdict="INVEST", confidence=0.9))
        assert len(matches) == 2

    def test_disabled_rules_skipped_in_evaluate(self):
        condition = Condition(field="verdict", operator="eq", value="INVEST")
        engine = AlertEngine([_rule("Disabled", condition, enabled=False)])
        assert engine.evaluate(_sample_event(verdict="INVEST")) == []

    def test_execute_actions_log(self, engine, caplog):
        """Log action writes to logger."""
        import logging
        with caplog.at_level(logging.INFO, logger="finscrape.alerts"):
            engine.execute_actions(
                _sample_event(),
                [Action(action_type="log")],
            )
        assert "ALERT [log]" in caplog.text

    def test_execute_actions_real(self, engine, caplog):
        """Real actions execute (telegram/webhook skip without proper config)."""
        import logging
        actions = [
            Action(action_type="telegram", config={"chat_id": "123"}),
            Action(action_type="webhook", config={}),
            Action(action_type="dashboard_push"),
        ]
        with caplog.at_level(logging.WARNING, logger="finscrape.alerts"):
            results = engine.execute_actions(_sample_event(), actions)
        assert len(results) == 3
        # Telegram skips without bot_token
        assert results[0]["action_type"] == "telegram"
        assert results[0]["status"] == "skipped"
        # Webhook skips without url
        assert results[1]["action_type"] == "webhook"
        assert results[1]["status"] == "skipped"
        # Dashboard skips if not configured
        assert results[2]["action_type"] == "dashboard_push"
        assert results[2]["status"] == "skipped"
