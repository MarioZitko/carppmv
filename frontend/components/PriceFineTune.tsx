"use client";

import { useEffect, useState } from "react";
import { formatEur } from "@/lib/format";

interface Props {
  priceEur: number;
  onChange: (price: number) => void;
}

const STEPS = [-1000, -100, 100, 1000];

// The slider window is anchored to a base price and only spans a fraction of
// it, so each drag step is a meaningful fine-tune instead of jumping over
// thousands of euros. The anchor is re-centered when a new vehicle/candidate
// sets a price outside the current window (rather than on every own change),
// otherwise dragging the slider would keep widening its own range.
const RANGE_FRACTION = 0.5;
const MIN_RANGE = 50000;
const STEP = 50;

function roundToStep(value: number) {
  return Math.round(value / STEP) * STEP;
}

/** Sidebar control for nudging the as-new price up/down and watching the
 * PPMV recompute live — useful when the catalogue/scrape price is only an
 * approximation of the actual listing price. */
export function PriceFineTune({ priceEur, onChange }: Props) {
  const [base, setBase] = useState(priceEur);

  const rangeWidth = Math.max(base * RANGE_FRACTION, MIN_RANGE);
  const min = Math.max(0, roundToStep(base - rangeWidth));
  const max = roundToStep(base + rangeWidth);

  useEffect(() => {
    if (priceEur < min || priceEur > max) {
      setBase(priceEur);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [priceEur]);

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm p-5 space-y-4">
      <h3 className="text-sm font-semibold text-[var(--text)]">Fino podešavanje cijene</h3>
      <p className="text-xs text-[var(--text-soft)]">
        Prilagodite cijenu ako se stvarna cijena vozila razlikuje od one pronađene u bazi/oglasu — PPMV se
        preračunava odmah.
      </p>
      <p className="text-xs text-[var(--text-soft)] italic">
        Napomena: baza sadrži cijene osnovnih izvedbi (trim varijanti) bez dodatne opreme. Stvarna cijena
        novog vozila može biti viša zbog paketa opreme i dodatnih značajki, a to može utjecati i na
        CO2 emisiju, a time i na iznos PPMV-a.
      </p>

      <div className="flex items-center justify-between font-mono-tab text-xl font-semibold text-[var(--text)]">
        {formatEur(priceEur)}
      </div>

      <input
        type="range"
        min={min}
        max={max}
        step={STEP}
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
        step={STEP}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)] transition-colors"
      />
    </div>
  );
}
