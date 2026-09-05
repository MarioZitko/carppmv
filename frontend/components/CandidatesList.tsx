"use client";

import { CatalogueCandidate } from "@/lib/types";
import { formatEur, formatDateHr } from "@/lib/format";

interface Props {
  candidates: CatalogueCandidate[];
  selectedCatalogueId?: number | null;
  onSelect: (candidate: CatalogueCandidate) => void;
  title?: string;
}

// Mirrors app/catalogue/matching.py ACCEPT_SCORE / CANDIDATE_FLOOR — frontend-only
// color tiering, the underlying score itself is never rescaled.
const SCORE_TIER_GOOD = 88; // matches backend ACCEPT_SCORE
const SCORE_TIER_OK = 75; // frontend-only midpoint toward CANDIDATE_FLOOR (62)

function scoreTierClassName(score: number): string {
  if (score >= SCORE_TIER_GOOD) return "bg-[var(--ok-bg)] text-[var(--ok)] border border-[var(--ok)]/30";
  if (score >= SCORE_TIER_OK) return "bg-[var(--warn-bg)] text-[var(--warn)] border border-[var(--warn)]/30";
  return "bg-[var(--err-bg)] text-[var(--err)] border border-[var(--err)]/30";
}

function headingOf(c: CatalogueCandidate): string {
  return `${c.brand} ${c.model}`.trim();
}

/** Ranked catalogue rows the fuzzy matcher found — brand/model/variant, price
 * and CO2 for each, so the user can pick the row that actually matches their
 * car instead of trusting a single auto-guess.
 *
 * A real query ("BMW" + "320d") routinely returns a dozen rows that are the
 * *same car* priced in different official price lists: identical brand, model,
 * variant, fuel and kW, all scoring 100, differing only in `valid_from` — and
 * across €10k of price and 12 g/km of CO2, both of which feed the tax directly.
 * So the row is laid out around what actually differs:
 *
 *  - `valid_from` is labelled ("cjenik od …") and sits with the price it
 *    qualifies, not buried unlabelled at the end of a spec line. An unlabelled
 *    date is the difference between a decidable list and an undecidable one.
 *  - The score badge is dropped entirely when every candidate scores the same.
 *    Twelve identical "100%" badges carry no information while reading as a
 *    confidence signal; the tiering below is only meaningful when scores differ.
 *  - When every row shares one heading, it is hoisted into the card header so
 *    the rows show only what separates them.
 *  - Text wraps rather than truncating. At 375px the heading and variant are
 *    exactly the lines that overflow, i.e. the ones telling rows apart.
 */
export function CandidatesList({ candidates, selectedCatalogueId, onSelect, title }: Props) {
  if (candidates.length === 0) return null;

  const allSameScore = candidates.every(
    (c) => Math.round(c.score) === Math.round(candidates[0].score),
  );
  const sharedHeading = candidates.every((c) => headingOf(c) === headingOf(candidates[0]))
    ? headingOf(candidates[0])
    : null;

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm overflow-hidden">
      <div className="px-4 py-2.5 border-b border-[var(--border)] bg-[var(--surface-alt)]">
        <h3 className="text-sm font-semibold text-[var(--text)]">
          {title ?? "Pronađeni zapisi u bazi vozila"}
          {sharedHeading ? <span className="font-normal"> — {sharedHeading}</span> : null}
        </h3>
        <p className="text-xs text-[var(--text-soft)]">
          Odaberite redak koji odgovara vašem vozilu ({candidates.length}). Preuzet će se njegova cijena i CO2.
        </p>
        <p className="text-xs text-[var(--text-soft)] mt-0.5">
          Isto vozilo pojavljuje se u više službenih cjenika. Odaberite cjenik koji vrijedi za godinu
          proizvodnje vašeg vozila — cijena i CO2 razlikuju se među njima.
        </p>
      </div>
      <ul className="divide-y divide-[var(--border)] max-h-[34rem] sm:max-h-[30rem] overflow-y-auto">
        {candidates.map((c, i) => {
          const active = selectedCatalogueId != null && selectedCatalogueId === c.catalogue_id;
          return (
            <li key={`${c.catalogue_id ?? "null"}-${c.brand}-${c.model}-${c.variant}-${c.valid_from}-${i}`}>
              <button
                type="button"
                onClick={() => onSelect(c)}
                className={`w-full text-left px-4 py-3 flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4 transition-colors ${
                  active ? "bg-[var(--primary-soft)]" : "hover:bg-[var(--surface-alt)]"
                }`}
              >
                <div className="min-w-0">
                  {sharedHeading ? null : (
                    <p className="text-sm font-medium text-[var(--text)]">
                      {headingOf(c)}
                    </p>
                  )}
                  <p className="text-xs text-[var(--text-soft)]">{c.variant}</p>
                  <p className="text-xs text-[var(--text-soft)] mt-0.5">
                    {c.fuel_type ?? "—"} · {c.power_kw ? `${c.power_kw} kW` : "—"} ·{" "}
                    {c.co2_standard ?? "—"}
                  </p>
                </div>
                <div className="text-left sm:text-right shrink-0">
                  <p className="font-mono-tab text-base font-semibold text-[var(--text)]">
                    {formatEur(c.price_eur)}
                  </p>
                  <p className="text-xs text-[var(--text-soft)]">
                    cjenik od {formatDateHr(c.valid_from)}
                  </p>
                  <p className="font-mono-tab text-xs text-[var(--text-soft)]">
                    {c.co2_g_km !== null ? `${c.co2_g_km} g/km CO2` : "CO2 nepoznat"}
                  </p>
                  {active ? (
                    <span className="inline-block mt-1 text-[10px] px-2 py-0.5 rounded-full bg-[var(--primary)] text-white">
                      odabrano
                    </span>
                  ) : allSameScore ? null : (
                    <span
                      className={`inline-block mt-1 text-[10px] px-2 py-0.5 rounded-full ${scoreTierClassName(c.score)}`}
                    >
                      podudarnost teksta {Math.round(c.score)}%
                    </span>
                  )}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
