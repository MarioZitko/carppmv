import { PPMVResponse } from "@/lib/types";
import { formatEur, formatPercent } from "@/lib/format";

interface Props {
  result: PPMVResponse;
  updating?: boolean;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between py-2 border-b border-[var(--border)] last:border-b-0">
      <span className="text-sm text-[var(--text-soft)]">{label}</span>
      <span className="font-mono-tab text-sm text-[var(--text)]">{value}</span>
    </div>
  );
}

export function PPMVBreakdownCard({ result, updating }: Props) {
  const b = result.breakdown;
  return (
    <div
      className={`rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm overflow-hidden transition-opacity ${
        updating ? "opacity-60" : ""
      }`}
    >
      <div className="px-5 py-4 border-b border-[var(--border)] flex items-baseline justify-between bg-[var(--surface-alt)]">
        <h3 className="text-sm font-semibold text-[var(--text)]">Raščlamba PPMV-a</h3>
        <span className="text-xs text-[var(--text-soft)]">CO2 standard: {result.co2_standard_used}</span>
      </div>
      <div className="px-5 py-2">
        <Row label="Vrijednosna komponenta (novo vozilo)" value={formatEur(b.as_new_value_component)} />
        <Row label="Ekološka komponenta (novo vozilo)" value={formatEur(b.as_new_eco_component)} />
        <Row label="Ukupno kao za novo vozilo" value={formatEur(b.as_new_total)} />
        <Row label="Faktor umanjenja za vrstu vozila" value={`× ${b.vehicle_reduction_factor.toFixed(2)}`} />
        <Row label="Starost vozila" value={`${b.months_old} mjeseci`} />
        <Row label="Preostala vrijednost (amortizacija)" value={formatPercent(b.depreciation_percent)} />
      </div>
      <div className="px-5 py-4 border-t border-[var(--border)] flex items-baseline justify-between bg-gradient-to-r from-[var(--primary-soft)] to-transparent">
        <span className="text-sm font-medium text-[var(--text)]">Procijenjeni PPMV</span>
        <span className="font-mono-tab text-2xl font-bold text-[var(--primary-dark)]">
          {formatEur(b.final_ppmv)}
        </span>
      </div>
    </div>
  );
}
