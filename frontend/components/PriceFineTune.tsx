"use client";

import { formatEur } from "@/lib/format";

interface Props {
  priceEur: number;
  onChange: (price: number) => void;
}

const STEPS = [-1000, -100, 100, 1000];

/** Sidebar control for nudging the as-new price up/down and watching the
 * PPMV recompute live — useful when the catalogue/scrape price is only an
 * approximation of the actual listing price. */
export function PriceFineTune({ priceEur, onChange }: Props) {
  const min = 0;
  const max = Math.max(priceEur * 2, priceEur + 20000, 20000);

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm p-5 space-y-4">
      <h3 className="text-sm font-semibold text-[var(--text)]">Fino podešavanje cijene</h3>
      <p className="text-xs text-[var(--text-soft)]">
        Prilagodite cijenu ako se stvarna cijena vozila razlikuje od one pronađene u bazi/oglasu — PPMV se
        preračunava odmah.
      </p>

      <div className="flex items-center justify-between font-mono-tab text-xl font-semibold text-[var(--text)]">
        {formatEur(priceEur)}
      </div>

      <input
        type="range"
        min={min}
        max={max}
        step={50}
        value={Math.min(Math.max(priceEur, min), max)}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[var(--primary)]"
      />

      <div className="grid grid-cols-4 gap-2">
        {STEPS.map((step) => (
          <button
            key={step}
            type="button"
            onClick={() => onChange(Math.max(0, priceEur + step))}
            className="rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] py-1.5 text-xs font-medium text-[var(--text)] hover:border-[var(--primary)] hover:text-[var(--primary)] transition-colors"
          >
            {step > 0 ? `+${step}` : step}
          </button>
        ))}
      </div>

      <input
        type="number"
        value={priceEur}
        min={0}
        step={50}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)] transition-colors"
      />
    </div>
  );
}
