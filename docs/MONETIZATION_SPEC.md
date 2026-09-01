# Monetization Implementation Spec

> **STATUS: §1 (carVertical) is live** — see
> `frontend/components/CarVerticalCard.tsx` and `frontend/.env.example`.
> §2 (AdSense) is still a deferred decision, gated on content pages and
> traffic, and is the reason this doc is still here.

## 1. carVertical Affiliate (primary)

### How it works
After PPMV result is shown, display a "Provjeri povijest vozila" (Check vehicle history) CTA button.
The link is pre-filled with the VIN extracted from the scrape.

### Affiliate link format
```
https://www.carvertical.com/hr/landing?vin={VIN}&utm_source=kalkulatoruvoza&utm_medium=affiliate&utm_campaign=ppmv_result
```

Replace `/hr/` with the correct locale slug once affiliate account is created and you have your ref/partner ID — the final link format will be provided by carVertical's dashboard (Post Affiliate Pro). It will look like:
```
https://www.carvertical.com/hr/landing?vin={VIN}&a_aid={YOUR_AFFILIATE_ID}
```

### Placement rules
- Show ONLY on the PPMV result page, after a successful calculation.
- Only render the button if VIN is present in the scraped data — never show a broken/empty VIN link.
- If VIN is unavailable, omit the button entirely (don't show a generic carVertical link without VIN).

### UI copy (Croatian)
```
Button:  "Provjeri povijest vozila →"
Subtext: "Provjeri kilometražu, štete i vlasništvo na carVertical (partnerski link)"
```

### Tracking
Cookie-based via carVertical's Post Affiliate Pro — no backend work needed on your side.
Join at: https://www.carvertical.com/affiliate-program

---

## 2. AdSense (secondary, impression-based)

### Key fact
AdSense moved to CPM (impression-based) in late 2023 — users do NOT need to click ads for you to earn. Every page load with a visible ad earns a small amount (~$2–6 RPM for EU/Croatian traffic).

### When to add
Do NOT add AdSense until:
- Site has real content pages (PPMV guide, import rules explanation — ~15–30 pages)
- ~50–100 daily visitors consistently
- AdSense approval requires this; bare calculator alone will be rejected for "low value content"

### Placement (when approved)
- One ad unit above the fold on content/guide pages
- One ad unit below the PPMV result (not blocking the carVertical CTA)
- Do NOT place ads on the calculator input form itself

### Revenue expectation
Hobby scale (~1,000–5,000 pageviews/month) = ~$2–25/month. Treat as negligible.
carVertical affiliate at 4€/conversion will outperform AdSense significantly at this traffic level.

---

## 3. Priority order

1. **carVertical affiliate** — implement now, zero setup cost, high intent users, no approval needed
2. **AdSense** — deferred until content pages exist and traffic threshold is met
