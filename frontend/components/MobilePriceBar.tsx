"use client";

import { PPMVResponse } from "@/lib/types";
import { formatEur } from "@/lib/format";

interface Props {
  result: PPMVResponse | null;
  updating?: boolean;
  hint?: string | null;
}

/** Sticky bottom bar shown only on mobile (hidden from `lg` up, where the
 * price sidebar is already visible without scrolling). Keeps the live PPMV
 * total in view the whole time the user is filling in the form, instead of
 * it only appearing once they scroll past the entire form. Tapping it jumps
 * straight to the full breakdown card. */
export function MobilePriceBar({ result, updating, hint }: Props) {
  return (
    <a
      href="#price-panel"
      className={`lg:hidden fixed inset-x-0 bottom-0 z-20 border-t border-[var(--border)] bg-[var(--surface)]/95 backdrop-blur px-4 py-3 shadow-[0_-4px_16px_rgba(0,0,0,0.08)] transition-opacity ${
        updating ? "opacity-70" : ""
      }`}
    >
      <div className="mx-auto max-w-6xl flex items-center justify-between gap-3">
        {result ? (
          <>
            <span className="text-xs font-medium uppercase tracking-wide text-[var(--text-soft)]">
              Procijenjeni PPMV
            </span>
            <span className="font-mono-tab text-lg font-bold text-[var(--primary-dark)]">
              {formatEur(result.breakdown.final_ppmv)}
            </span>
          </>
        ) : (
          <span className="text-xs text-[var(--text-soft)]">
            {hint ?? "Popunite podatke o vozilu za izračun PPMV-a"}
          </span>
        )}
      </div>
    </a>
  );
}
