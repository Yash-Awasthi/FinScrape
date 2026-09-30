"""WorldFin ingestion worker — continuous scrape→analyze→judge→geocode→ingest.

Separate long-running process (own asyncio loop). Blocking finscrape work (scrapers,
LLM, market data) runs in a threadpool so it never stalls the loop. Reuses the
finscrape brain (FinScrapePipeline._analyze_article) and the server ingest/geocode layer.
"""
