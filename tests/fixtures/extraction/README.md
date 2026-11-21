# Extraction fixtures (plan M1.5)

Ten synthetic news pages, one per site shape the scraper meets in production: a wire
template (`<article>`), a broadcaster (`<main>` with text blocks), a paywalled daily
(`itemprop` body), a live-blog page, a short wire copy, an Asia markets desk, a
terminal-style page, a Middle-East desk, a weekly essay and an ad-heavy local paper.

Every page carries the same six-sentence body wrapped in the chrome that used to leak
into the model: nav links, a cookie banner, an ad rail, a related-links list and a
footer. `tests/test_article_extraction.py` asserts the body comes back and the chrome
never does.

**Provenance:** written for this repo on 2026-11-24 (not captured from the live web),
so the test runs offline and cannot rot with a site redesign. They are shape fixtures,
not accuracy fixtures — the real sites' markup is richer, which is why M2.1's gold set
carries the accuracy claim instead.
