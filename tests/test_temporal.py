"""Tests for the temporal extraction module."""

from datetime import datetime

import pytest

from finscrape.analysis.nlp import FinancialNLP, NLPResult
from finscrape.analysis.temporal import (
    TemporalExtractor,
    TemporalReference,
    get_next_catalyst_date,
)

# Fixed reference date for deterministic tests
REF = datetime(2026, 4, 14)


@pytest.fixture
def extractor():
    return TemporalExtractor()


# ---------- Explicit date extraction ----------

class TestExplicitDates:
    def test_month_day_year(self, extractor):
        refs = extractor.extract("The meeting is on March 15, 2026.")
        dates = [r for r in refs if r.ref_type == "date" and r.resolved_date]
        assert any(r.resolved_date == "2026-03-15" for r in dates)

    def test_month_day_year_no_comma(self, extractor):
        refs = extractor.extract("Deadline is January 5 2026.")
        dates = [r for r in refs if r.ref_type == "date" and r.resolved_date]
        assert any(r.resolved_date == "2026-01-05" for r in dates)

    def test_abbreviated_month(self, extractor):
        refs = extractor.extract("Results due Sep 30, 2026.")
        dates = [r for r in refs if r.ref_type == "date" and r.resolved_date]
        assert any(r.resolved_date == "2026-09-30" for r in dates)

    def test_iso_date(self, extractor):
        refs = extractor.extract("Published on 2026-03-15 at noon.")
        dates = [r for r in refs if r.ref_type == "date"]
        assert any(r.resolved_date == "2026-03-15" for r in dates)

    def test_slash_date(self, extractor):
        refs = extractor.extract("Filed 15/03/2026 with the SEC.")
        dates = [r for r in refs if r.ref_type == "date"]
        assert any(r.resolved_date == "2026-03-15" for r in dates)

    def test_raw_text_preserved(self, extractor):
        refs = extractor.extract("March 15, 2026 is important.")
        dates = [r for r in refs if r.ref_type == "date" and r.resolved_date == "2026-03-15"]
        assert len(dates) >= 1
        assert "March 15, 2026" in dates[0].raw_text


# ---------- Quarter detection ----------

class TestQuarterDetection:
    def test_q_format(self, extractor):
        refs = extractor.extract("Revenue grew in Q1 2026.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert quarters[0].quarter == "Q1 2026"
        assert quarters[0].resolved_date == "2026-03-31"
        assert quarters[0].fiscal_year == 2026

    def test_q_short_year(self, extractor):
        refs = extractor.extract("Guidance for Q3 26 was raised.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert quarters[0].quarter == "Q3 2026"

    def test_q_apostrophe(self, extractor):
        refs = extractor.extract("Results for Q1'26 beat estimates.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert quarters[0].quarter == "Q1 2026"

    def test_nq_format(self, extractor):
        refs = extractor.extract("Strong results in 1Q26.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert quarters[0].quarter == "Q1 2026"

    def test_nq_four_digit_year(self, extractor):
        refs = extractor.extract("Outlook for 2Q2026 is positive.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert quarters[0].quarter == "Q2 2026"
        assert quarters[0].resolved_date == "2026-06-30"

    def test_ordinal_quarter(self, extractor):
        refs = extractor.extract("First quarter 2026 saw record growth.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert quarters[0].quarter == "Q1 2026"

    def test_ordinal_quarter_third(self, extractor):
        refs = extractor.extract("The third quarter 2025 was weak.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert quarters[0].quarter == "Q3 2025"
        assert quarters[0].resolved_date == "2025-09-30"

    def test_ordinal_quarter_with_of(self, extractor):
        refs = extractor.extract("In the second quarter of 2026, revenue rose.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert quarters[0].quarter == "Q2 2026"

    def test_all_quarter_end_dates(self, extractor):
        """Verify Q1-Q4 resolve to correct end-of-quarter dates."""
        for q_num, expected_date in [(1, "2026-03-31"), (2, "2026-06-30"),
                                      (3, "2026-09-30"), (4, "2026-12-31")]:
            refs = extractor.extract(f"Results for Q{q_num} 2026.")
            quarters = [r for r in refs if r.ref_type == "quarter"]
            assert quarters[0].resolved_date == expected_date, f"Q{q_num} mismatch"


# ---------- Fiscal year detection ----------

class TestFiscalYear:
    def test_fy_four_digit(self, extractor):
        refs = extractor.extract("Guidance for FY2026 was updated.")
        fy = [r for r in refs if r.ref_type == "fiscal_year"]
        assert len(fy) >= 1
        assert fy[0].fiscal_year == 2026
        assert fy[0].resolved_date == "2026-12-31"

    def test_fy_two_digit(self, extractor):
        refs = extractor.extract("FY26 revenue target raised.")
        fy = [r for r in refs if r.ref_type == "fiscal_year"]
        assert len(fy) >= 1
        assert fy[0].fiscal_year == 2026

    def test_fy_with_space(self, extractor):
        refs = extractor.extract("FY 2026 outlook is strong.")
        fy = [r for r in refs if r.ref_type == "fiscal_year"]
        assert len(fy) >= 1
        assert fy[0].fiscal_year == 2026

    def test_fiscal_year_long_form(self, extractor):
        refs = extractor.extract("The fiscal year 2026 results were strong.")
        fy = [r for r in refs if r.ref_type == "fiscal_year"]
        assert len(fy) >= 1
        assert fy[0].fiscal_year == 2026
        assert fy[0].resolved_date == "2026-12-31"


# ---------- Relative date handling ----------

class TestRelativeDates:
    def test_next_quarter(self, extractor):
        # April 14, 2026 is Q2 -> next quarter is Q3 -> 2026-09-30
        refs = extractor.extract("We expect improvement next quarter.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date == "2026-09-30"

    def test_last_quarter(self, extractor):
        # Q2 2026 -> last quarter is Q1 -> 2026-03-31
        refs = extractor.extract("Last quarter was strong.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date == "2026-03-31"

    def test_last_week(self, extractor):
        refs = extractor.extract("Sales surged last week.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date == "2026-04-07"

    def test_yesterday(self, extractor):
        refs = extractor.extract("Stock dropped yesterday.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date == "2026-04-13"

    def test_tomorrow(self, extractor):
        refs = extractor.extract("Report comes out tomorrow.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date == "2026-04-15"

    def test_today(self, extractor):
        refs = extractor.extract("Markets opened flat today.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date == "2026-04-14"

    def test_this_month(self, extractor):
        refs = extractor.extract("Earnings this month.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date == "2026-04-14"

    def test_next_month(self, extractor):
        refs = extractor.extract("IPO expected next month.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date == "2026-05-01"

    def test_year_over_year(self, extractor):
        refs = extractor.extract("Revenue grew 15% year-over-year.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        # Comparison patterns have no single resolved date
        assert rel[0].resolved_date is None

    def test_quarter_over_quarter(self, extractor):
        refs = extractor.extract("Margins improved quarter-over-quarter.", reference_date=REF)
        rel = [r for r in refs if r.ref_type == "relative"]
        assert len(rel) >= 1
        assert rel[0].resolved_date is None


# ---------- Earnings references ----------

class TestEarningsReferences:
    def test_earnings_call_on(self, extractor):
        refs = extractor.extract("Apple has an earnings call on April 25, 2026.")
        earn = [r for r in refs if r.ref_type == "earnings"]
        assert len(earn) >= 1
        assert "earnings call" in earn[0].raw_text.lower()

    def test_next_earnings(self, extractor):
        refs = extractor.extract("Investors await next earnings.")
        earn = [r for r in refs if r.ref_type == "earnings"]
        assert len(earn) >= 1

    def test_earnings_report(self, extractor):
        refs = extractor.extract("The quarterly earnings report showed strength.")
        earn = [r for r in refs if r.ref_type == "earnings"]
        assert len(earn) >= 1

    def test_reports_on(self, extractor):
        refs = extractor.extract("Tesla reports earnings on July 20.")
        earn = [r for r in refs if r.ref_type == "earnings"]
        assert len(earn) >= 1


# ---------- Deadline detection ----------

class TestDeadlineDetection:
    def test_deadline(self, extractor):
        refs = extractor.extract("The filing deadline is March 31.")
        dl = [r for r in refs if r.ref_type == "deadline"]
        assert len(dl) >= 1
        assert "deadline" in dl[0].raw_text.lower()

    def test_due_date(self, extractor):
        refs = extractor.extract("The due date for the proxy is May 1.")
        dl = [r for r in refs if r.ref_type == "deadline"]
        assert len(dl) >= 1

    def test_expires(self, extractor):
        refs = extractor.extract("The offer expires on June 15, 2026.")
        dl = [r for r in refs if r.ref_type == "deadline"]
        assert len(dl) >= 1

    def test_by_end_of(self, extractor):
        refs = extractor.extract("Must complete by end of Q2.")
        dl = [r for r in refs if r.ref_type == "deadline"]
        assert len(dl) >= 1


# ---------- get_next_catalyst_date ----------

class TestGetNextCatalystDate:
    def test_returns_nearest_future(self):
        refs = [
            TemporalReference(raw_text="Q1 2026", ref_type="quarter",
                              resolved_date="2026-03-31", quarter="Q1 2026"),
            TemporalReference(raw_text="Q3 2026", ref_type="quarter",
                              resolved_date="2026-09-30", quarter="Q3 2026"),
            TemporalReference(raw_text="Q2 2026", ref_type="quarter",
                              resolved_date="2026-06-30", quarter="Q2 2026"),
        ]
        result = get_next_catalyst_date(refs, reference_date=REF)
        assert result == "2026-06-30"

    def test_excludes_past_dates(self):
        refs = [
            TemporalReference(raw_text="Jan 5, 2026", ref_type="date",
                              resolved_date="2026-01-05"),
            TemporalReference(raw_text="Q1 2026", ref_type="quarter",
                              resolved_date="2026-03-31"),
        ]
        result = get_next_catalyst_date(refs, reference_date=REF)
        # Both are in the past relative to April 14 2026
        assert result is None

    def test_returns_none_for_empty(self):
        assert get_next_catalyst_date([]) is None

    def test_returns_none_no_resolved(self):
        refs = [
            TemporalReference(raw_text="next quarter", ref_type="relative"),
            TemporalReference(raw_text="earnings call", ref_type="earnings"),
        ]
        assert get_next_catalyst_date(refs, reference_date=REF) is None


# ---------- Empty / no-temporal text ----------

class TestEdgeCases:
    def test_empty_text(self, extractor):
        refs = extractor.extract("")
        assert refs == []

    def test_no_temporal_text(self, extractor):
        refs = extractor.extract("Apple stock rose 5% on strong demand.")
        # There might be spaCy DATE entities, but no regex-matched temporal refs
        # Just verify it doesn't crash and returns a list
        assert isinstance(refs, list)

    def test_context_is_populated(self, extractor):
        refs = extractor.extract("Revenue in Q1 2026 beat estimates by 10%.")
        quarters = [r for r in refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert len(quarters[0].context) > 0


# ---------- Integration with FinancialNLP.analyze ----------

class TestNLPIntegration:
    def test_analyze_includes_temporal_refs(self):
        nlp = FinancialNLP()
        result = nlp.analyze(
            "Apple Q1 2026 earnings beat",
            "Apple reported Q1 2026 earnings of $1.50 per share, beating estimates. "
            "The company expects strong results in Q2 2026. Next earnings call on July 20, 2026."
        )
        assert isinstance(result.temporal_refs, list)
        quarters = [r for r in result.temporal_refs if r.ref_type == "quarter"]
        assert len(quarters) >= 1
        assert any(r.quarter == "Q1 2026" for r in quarters)

    def test_get_next_catalyst_date_helper(self):
        nlp = FinancialNLP()
        result = nlp.analyze(
            "Apple earnings",
            "Apple will report next quarter. The earnings call on July 20, 2026 is anticipated. "
            "Fiscal year 2026 guidance will be updated."
        )
        catalyst = nlp.get_next_catalyst_date(result, reference_date=REF)
        # Should find July 20, 2026 or Q3 end or FY2026 end — all future from April 14
        assert catalyst is not None

    def test_nlp_result_has_temporal_refs_field(self):
        result = NLPResult()
        assert hasattr(result, "temporal_refs")
        assert result.temporal_refs == []

    def test_analyze_empty_text(self):
        nlp = FinancialNLP()
        result = nlp.analyze("", "No financial content here at all.")
        assert isinstance(result.temporal_refs, list)


# ---------- Single parse per analyze() call ----------

class TestSingleParsePerAnalyze:
    """
    analyze() used to parse the article text twice: once for entity extraction
    (via nlp.py's loader) and once more for temporal extraction (via a second,
    independent loader that temporal.py kept for itself). Both loaders now share
    one spaCy model, and analyze() parses the text once and passes that same doc
    into TemporalExtractor.extract().
    """

    def test_model_loaded_once_and_doc_built_once(self, monkeypatch):
        get_nlp_calls = {"count": 0}
        doc_build_calls = {"count": 0}

        class FakeDoc:
            ents = []

        def fake_model(text):
            doc_build_calls["count"] += 1
            return FakeDoc()

        def fake_get_nlp():
            get_nlp_calls["count"] += 1
            return fake_model

        import finscrape.analysis.nlp as nlp_module
        monkeypatch.setattr(nlp_module, "_get_nlp", fake_get_nlp)

        nlp = FinancialNLP()
        nlp.analyze(
            "Apple Q1 2026 earnings beat",
            "Apple reported Q1 2026 earnings of $1.50 per share, beating estimates.",
        )

        assert get_nlp_calls["count"] == 1
        assert doc_build_calls["count"] == 1
