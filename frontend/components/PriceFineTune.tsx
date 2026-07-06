"use client";

import { useEffect, useState } from "react";
import { formatEur } from "@/lib/format";

interface Props {
  priceEur: number;
  onChange: (price: number) => void;
  /** Bump this (e.g. with an incrementing counter) whenever priceEur is being
   * set from a new authoritative source — a parsed listing URL or a picked
   * catalogue candidate — rather than from the user fine-tuning the price
   * themselves. Forces the extras anchor to reset to the new price even when
   * that price happens to already fall inside the current slider window. */
  anchorToken?: number;
}

const STEPS = [-1000, -100, 100, 1000];

// Extras only ever push the price up from the catalogue's base-trim (no
// extras) price, so the control is anchored to that base price rather than
// an arbitrary absolute window around whatever priceEur currently is.
const EXTRAS_PERCENTS = [0, 5, 10, 15, 20, 30];
const SLIDER_MAX_FRACTION = 0.4; // slider's outer bound: anchor * 1.4
const SNAP_THRESHOLD_FRACTION = 0.01; // snap when within 1% of the window width of a mark
const STEP = 50;

function roundToStep(value: number) {
  return Math.round(value / STEP) * STEP;
}

/** Price after adding `pct`% worth of extras on top of the anchor price. */
function priceForPercent(anchor: number, pct: number) {
  return roundToStep(anchor * (1 + pct / 100));
}

/** Finds the extras percent whose price is within the snap threshold of
 * `value`, or null if none is close enough (a free/manual value). */
function nearestSnapPercent(value: number, anchor: number, max: number): number | null {
  const threshold = (max - anchor) * SNAP_THRESHOLD_FRACTION;
  for (const pct of EXTRAS_PERCENTS) {
    if (Math.abs(value - priceForPercent(anchor, pct)) <= threshold) return pct;
  }
  return null;
}

/** Sidebar control for dialing in how much extra equipment the actual
 * vehicle has on top of the catalogue's base-trim price, and watching the
 * PPMV recompute live. The anchor (no-extras price) only moves when
 * `anchorToken` changes — i.e. when a new listing/candidate price arrives —
 * never while the user is just dragging/clicking within the control. */
export function PriceFineTune({ priceEur, onChange, anchorToken }: Props) {
  const [anchor, setAnchor] = useState(priceEur);
  const [selectedPct, setSelectedPct] = useState<number | null>(0);

  const min = anchor > 0 ? roundToStep(anchor) : 0;
  const max = anchor > 0 ? roundToStep(anchor * (1 + SLIDER_MAX_FRACTION)) : 50000;

  useEffect(() => {
    setAnchor(priceEur);
    setSelectedPct(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorToken]);

  function applyPercent(pct: number) {
    setSelectedPct(pct);
    onChange(priceForPercent(anchor, pct));
  }

  function handleSliderChange(raw: number) {
    const snapped = nearestSnapPercent(raw, anchor, max);
    if (snapped !== null) {
      setSelectedPct(snapped);
      onChange(priceForPercent(anchor, snapped));
    } else {
      setSelectedPct(null);
      onChange(roundToStep(raw));
    }
  }

  function handleStep(step: number) {
    const next = Math.max(0, priceEur + step);
    setSelectedPct(nearestSnapPercent(next, anchor, max));
    onChange(next);
  }

  function handleNumberChange(raw: string) {
    const next = Number(raw) || 0;
    setSelectedPct(nearestSnapPercent(next, anchor, max));
    onChange(next);
  }

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm p-5 space-y-4">
      <h3 className="text-sm font-semibold text-[var(--text)]">Fino podešavanje cijene</h3>
      <div className="rounded-xl border border-[var(--warn)]/30 bg-[var(--warn-bg)] px-3.5 py-2.5">
        <p className="text-sm text-[var(--warn)] font-medium leading-snug">
          Napomena: baza sadrži cijene osnovnih izvedbi (trim varijanti) bez dodatne opreme. Stvarna cijena
          novog vozila može biti viša zbog paketa opreme i dodatnih značajki, a to može utjecati i na
          CO2 emisiju, a time i na iznos PPMV-a.
        </p>
      </div>

      <div className="flex items-center justify-between font-mono-tab text-xl font-semibold text-[var(--text)]">
        {formatEur(priceEur)}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {EXTRAS_PERCENTS.map((pct) => {
          const isActive = selectedPct === pct;
          return (
            <button
              key={pct}
              type="button"
              onClick={() => applyPercent(pct)}
              className={`rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors border ${
                isActive
                  ? "bg-[var(--primary-soft)] text-[var(--primary)] border-[var(--primary)]"
                  : "bg-[var(--surface-alt)] text-[var(--text-soft)] border-[var(--border)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
              }`}
            >
              {pct === 0 ? "Bez dodatne opreme" : `+${pct}%`}
            </button>
          );
        })}
      </div>

      <input
        type="range"
        list="extras-ticks"
        min={min}
        max={max}
        step={STEP}
        value={Math.min(Math.max(priceEur, min), max)}
        onChange={(e) => handleSliderChange(Number(e.target.value))}
        className="w-full accent-[var(--primary)]"
      />
      {/* Tick marks render in Chromium/Firefox; Safari ignores <datalist> on
          range inputs, but the JS snapping above works everywhere regardless. */}
      <datalist id="extras-ticks">
        {EXTRAS_PERCENTS.map((pct) => (
          <option key={pct} value={priceForPercent(anchor, pct)} />
        ))}
      </datalist>

      <div className="grid grid-cols-4 gap-2">
        {STEPS.map((step) => (
          <button
            key={step}
            type="button"
            onClick={() => handleStep(step)}
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
        onChange={(e) => handleNumberChange(e.target.value)}
        className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)] transition-colors"
      />
    </div>
  );
}
