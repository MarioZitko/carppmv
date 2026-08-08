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

/** Ranked catalogue rows the fuzzy matcher found — brand/model/variant, price
 * and CO2 for each, so the user can pick the row that actually matches their
 * car instead of trusting a single auto-guess. */
export function CandidatesList({ candidates, selectedCatalogueId, onSelect, title }: Props) {
  if (candidates.length === 0) return null;

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm overflow-hidden">
      <div className="px-4 py-2.5 border-b border-[var(--border)] bg-[var(--surface-alt)]">
        <h3 className="text-sm font-semibold text-[var(--text)]">
          {title ?? "Pronađeni zapisi u bazi vozila"}
        </h3>
        <p className="text-xs text-[var(--text-soft)]">
          Odaberite redak koji odgovara vašem vozilu ({candidates.length}) — preuzima njegovu cijenu i CO2.
        </p>
      </div>
      <ul className="divide-y divide-[var(--border)] max-h-80 overflow-y-auto">
        {candidates.map((c, i) => {
          const active = selectedCatalogueId != null && selectedCatalogueId === c.catalogue_id;
          return (
            <li key={`${c.catalogue_id ?? "null"}-${c.brand}-${c.model}-${c.variant}-${c.valid_from}-${i}`}>
              <button
                type="button"
                onClick={() => onSelect(c)}
                className={`w-full text-left px-4 py-2.5 flex items-center justify-between gap-4 transition-colors ${
                  active ? "bg-[var(--primary-soft)]" : "hover:bg-[var(--surface-alt)]"
                }`}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-[var(--text)] truncate">
                    {c.brand} {c.model}
                  </p>
                  <p className="text-xs text-[var(--text-soft)] truncate">{c.variant}</p>
                  <p className="text-xs text-[var(--text-soft)] mt-0.5">
                    {c.fuel_type ?? "—"} · {c.power_kw ? `${c.power_kw} kW` : "—"} ·{" "}
                    {c.co2_standard ?? "—"} · {formatDateHr(c.valid_from)}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono-tab text-sm font-semibold text-[var(--text)]">
                    {formatEur(c.price_eur)}
                  </p>
                  <p className="font-mono-tab text-xs text-[var(--text-soft)]">
                    {c.co2_g_km !== null ? `${c.co2_g_km} g/km CO2` : "CO2 nepoznat"}
                  </p>
                  <span
                    className={`inline-block mt-1 text-[10px] px-2 py-0.5 rounded-full ${
                      active ? "bg-[var(--primary)] text-white" : scoreTierClassName(c.score)
                    }`}
                  >
                    {active ? "odabrano" : `podudarnost ${Math.round(c.score)}%`}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
