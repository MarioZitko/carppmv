"use client";

import { useState } from "react";
import { ParsedFields } from "@/lib/types";
import { formatEur } from "@/lib/format";

interface Props {
  parsed: ParsedFields;
  warnings: string[];
}

const FUEL_LABELS: Record<string, string> = {
  diesel: "Dizel",
  dizel: "Dizel",
  petrol: "Benzin",
  benzin: "Benzin",
  gasoline: "Benzin",
  electric: "Električno",
  elektro: "Električno",
};

function field(label: string, value: string | number | null) {
  return (
    <div key={label} className="flex justify-between py-1.5 border-b border-[var(--border)] last:border-b-0">
      <span className="text-[var(--text-soft)]">{label}</span>
      <span className="font-mono-tab text-[var(--text)]">{value === null || value === "" ? "—" : value}</span>
    </div>
  );
}

/** Compact by design — this is a "what did we scrape" verification aid, not
 * primary UI, so it stays collapsed by default (even when there are
 * warnings) rather than pushing the vehicle form down the page. The warning
 * count stays visible in the collapsed header so it's not missed. */
export function ParsedFieldsCard({ parsed, warnings }: Props) {
  const [open, setOpen] = useState(false);
  const fuelLabel = parsed.fuel_type ? FUEL_LABELS[parsed.fuel_type.toLowerCase()] ?? parsed.fuel_type : null;

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-2 flex items-center justify-between text-left bg-[var(--surface-alt)]"
      >
        <span className="flex items-center gap-2 text-xs font-semibold text-[var(--text)]">
          Podaci pronađeni u oglasu
          {warnings.length > 0 && (
            <span className="rounded-full bg-[var(--warn-bg)] text-[var(--warn)] text-[10px] font-medium px-1.5 py-0.5">
              {warnings.length} {warnings.length === 1 ? "upozorenje" : "upozorenja"}
            </span>
          )}
        </span>
        <span className="text-xs text-[var(--text-soft)]">{open ? "sakrij" : "prikaži"}</span>
      </button>

      {open && (
        <>
          <div className="px-4 pb-3 pt-1 text-sm">
            {field("Marka", parsed.brand)}
            {field("Model", parsed.model)}
            {field("Varijanta", parsed.variant)}
            {field("Vrsta goriva", fuelLabel)}
            {field("Prva registracija", parsed.first_registration)}
            {field("Snaga", parsed.power_kw !== null ? `${parsed.power_kw} kW` : null)}
            {field("CO2", parsed.co2_g_km !== null ? `${parsed.co2_g_km} g/km` : null)}
            {field("Cijena", formatEur(parsed.price_eur))}
            {field("Broj sjedala", parsed.seat_count)}
          </div>

          {warnings.length > 0 && (
            <div className="border-t border-[var(--border)] bg-[var(--warn-bg)] px-4 py-2.5 space-y-1">
              {warnings.map((w) => (
                <p key={w} className="text-sm text-[var(--warn)]">
                  {w}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
