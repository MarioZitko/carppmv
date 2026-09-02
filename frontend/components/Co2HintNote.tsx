"use client";

import { WikipediaCo2Hint } from "@/lib/types";

interface Props {
  hint: WikipediaCo2Hint | null | undefined;
  /** Engine designation, shown once the user has picked a variant themselves —
   * it's the thing they chose, so it's more use than the article title. */
  engineCode?: string | null;
  /** Opens the engine picker. Omitted when the listing gave us no brand. */
  onBrowse?: () => void;
}

/** The last-resort CO2 estimate: a range, its provenance, and nothing else.
 *
 * Deliberately NOT styled like CandidatesList — that component's score badge
 * uses the ok/warn/err palette and a match percentage, which read as "the
 * system is confident, accept this." This tier is the opposite claim: it
 * answers for ~36% of vehicles and only ~55% of those answers contain the true
 * value. So the treatment is muted surface, no status color, no score, and the
 * range at body weight rather than as a headline figure.
 *
 * Display only. It never writes to the CO2 field — not on load, and not behind
 * a button. A value this uncertain reaching the tax base is what
 * docs/WIKIPEDIA_CO2_PLAN.md §0 forbids, and the field stays the user's to
 * fill. The `procjena` pill plus the "Wikipedia:" prefix are the whole
 * disclaimer; a sentence spelling it out was tried and was more text than the
 * fact deserved. */
export function Co2HintNote({ hint, engineCode, onBrowse }: Props) {
  if (!hint) return null;

  const range =
    hint.co2_min_g_km === hint.co2_max_g_km
      ? `${hint.co2_min_g_km}`
      : `${hint.co2_min_g_km}–${hint.co2_max_g_km}`;

  return (
    <div className="mt-1.5 rounded-xl border border-[var(--border)] bg-[var(--surface-alt)] px-2.5 py-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="text-[10px] uppercase tracking-wide font-medium text-[var(--text-soft)] border border-[var(--border)] rounded-full px-1.5 py-0.5">
        procjena
      </span>
      <span className="text-xs text-[var(--text-soft)]">
        Wikipedia:{" "}
        <span className="font-mono-tab text-[var(--text)]">{range} g/km</span>
      </span>
      <a
        href={hint.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="ml-auto text-xs text-[var(--primary)] hover:underline"
      >
        {engineCode ?? hint.model_article_title} ↗
      </a>
      {onBrowse && (
        <button
          type="button"
          onClick={onBrowse}
          className="text-xs text-[var(--primary)] hover:underline"
        >
          promijeni motor
        </button>
      )}
    </div>
  );
}
