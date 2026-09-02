"""de.wikipedia CO2 pipeline (docs/WIKIPEDIA_CO2_PLAN.md).

Offline/batch only — same category as app/data/catalogues/ingest.py. Nothing
here is called from the /calculate request path.

Phase 0 (crawl.py + sections.py) finds each brand's model articles and caches
their raw wikitext in WikipediaRawArticle. Phase 1 (llm_sections.py) is the
fallback that asks an LLM which heading lists models, and runs only for brands
whose mechanical section match failed.
"""
