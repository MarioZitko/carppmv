# Legal + SEO Content Plan — kalkulatoruvoza.com

> Companion to MASTER_PLAN_v7.md. Doesn't block PPMV calculator build (§0 of master plan).
> Sequence this in parallel or after PPMV ships — legal pages before any real traffic,
> SEO content pages before/around AdSense application.

---

## Phase 0 — Legal pages (before any public traffic, ~1 day)

Not SEO, but blocking: GDPR applies the moment you set a cookie or hash an IP, which the
backend already does (`client_ip_hash`, `ApifyEvent`).

| Page | URL | Content |
|---|---|---|
| Privacy Policy | `/privatnost` | What's collected (hashed IP, no raw IP per CLAUDE.md; Apify event logs; cookies), why, retention, GDPR rights (access/delete), contact for requests, mention carVertical + AdSense as third-party processors once live |
| Cookie Policy | `/kolacici` | Cookie table: essential (session), affiliate tracking (carVertical), analytics if added, AdSense (once live). Consent banner links here. |
| Affiliate disclosure | inline near carVertical CTA + own line on Privacy Policy | One line: "Kalkulator uvoza koristi partnerski (affiliate) link prema carVertical — ako kliknete i kupite provjeru, možemo dobiti proviziju." |
| Tax disclaimer | inline on result page + footer link | "Ovo je procjena temeljena na javno dostupnim propisima, nije službeno porezno mišljenje. Za konačan iznos obratite se Carinskoj upravi." — covers liability on the PPMV number specifically |

Skip: Terms of Sale, Refund Policy, Returns — no transactions happen on your site.

**Deliverable:** 2 standalone pages (Privacy, Cookie) + 2 inline disclosure snippets + cookie consent banner component.

---

## Phase 1 — Tool page hardening (before Phase 2, ~2-3 days)

The calculator page itself needs supporting content before it's a good AdSense/SEO candidate —
bare calculator = "low value content" rejection risk.

| Addition | Where | Content |
|---|---|---|
| "Kako radi" section | Below calculator, same page | 2-3 short paragraphs: what PPMV is, what inputs are needed, what output means. Not a full guide — just enough context to not look like a bare form. |
| FAQ block | Below calculator, same page | 5-8 Q&As: "Što je PPMV", "Trebam li platiti ako uvozim iz EU", "Odakle da znam CO2 vrijednost", "Je li ovo službeni izračun". Mark up with FAQPage schema. |
| About/methodology | New page `/o-kalkulatoru` | What sources you cite (NN 156/22, Pravilnik), how the formula works at a high level, link to full guide (Phase 2). Doubles as trust signal for AdSense review. |

**Deliverable:** 1 new page + 2 sections added to the calculator page + schema markup.

---

## Phase 2 — Pillar content (SEO core, ~1 week, can be spread out)

Build order matches ranking difficulty — narrow/specific pages first (easier to rank, validates
the content approach), pillar guide last (harder, benefits from internal links from the narrow
pages already being indexed).

### 2a. NEDC vs WLTP explainer — `/nedc-vs-wltp`
Narrow, high-intent, low-competition. Content:
- What NEDC and WLTP are (one paragraph each)
- The 1.1.2021 cutoff and why it matters for PPMV
- How to tell which one applies to your car (registration date)
- Where to find your CO2 value (COC, oglasi, manufacturer)

### 2b. Vodič za uvoz automobila iz Njemačke — `/vodic-uvoz-njemacka`
Process guide, taps real search intent around mobile.de/autobid.de/AutoScout24 audience.
Content:
- Steps: find car → check specs/CO2 → calculate PPMV → transport → homologacija → registracija
- Documents needed (COC, račun, prijevoz)
- Common mistakes (wrong CO2 assumption, missing COC)
- CTA back to calculator at each relevant step

### 2c. Kako se izračunava PPMV — `/kako-se-izracunava-ppmv` (the pillar page)
The authority page other pages link into. Content:
- Full formula walkthrough (VN+PC+ON+EN) in plain language
- NEDC/WLTP split (links to 2a for detail)
- Depreciation table concept (not full table — that's the calculator's job)
- Worked example using the Audi A5 regression case — real numbers, real transparency
- Links to narodne-novine.nn.hr as primary source

### 2d. Standalone FAQ — `/cesta-pitanja`
Canonical version of the Phase 1 FAQ, expanded (15-20 Q&As pulled from all pages), FAQPage
schema, internal links to every other page.

**Deliverable:** 4 pages, ~800-1500 words each, internally linked, each with a clear CTA back
to the calculator.

---

## Phase 3 — Blog / case studies (optional, ongoing, only if maintained)

Skip entirely unless you'll post at least monthly — a stale blog actively hurts more than no
blog. If pursued:
- Real worked examples (anonymized), like the Audi A5 case, as short case-study posts
- Law/table changes when they happen
- No generic "top 10 cars to import" listicle content — thin, doesn't fit the site's authority

**Deliverable:** none required to launch. Revisit after Phase 2 is indexed and you have traffic
data on what people actually search for.

---

## Summary timeline

```
Phase 0 (legal)       ─┐
                        ├─ before public launch
Phase 1 (tool hardening) ┘

Phase 2 (pillar content) ── before/around AdSense application
  2a → 2b → 2c → 2d (sequential, ~1 page every 1-2 days)

Phase 3 (blog)         ── deferred, optional, revisit post-launch
```

---

## Claude Code model recommendation

**Sonnet is enough for all of this.** Reasoning:
- Legal pages (Phase 0): templated compliance text in Croatian, no complex logic — Sonnet handles this well, especially with the specific technical facts (client_ip_hash, ApifyEvent, carVertical terms) already in your memory/CLAUDE.md to ground it accurately.
- Content pages (Phase 1-2): explanatory writing grounded in your own MASTER_PLAN_v7.md tax tables and formula — Sonnet doesn't need Opus-level reasoning to write an accurate NEDC/WLTP explainer once the facts are given.
- Where it matters more: if you ask Claude Code to *also* verify legal citations against narodne-novine.nn.hr live, or reconcile subtle formula edge cases while drafting the pillar page, give it web search access and let it check sources — the model tier matters less than tool access here.

Reserve Opus/higher tiers for the actual PPMV engine work (formula edge cases, catalogue
matching tuning, scraper reliability) where correctness bugs are costly — not for writing
Croatian marketing/legal copy.
