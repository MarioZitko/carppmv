/** Reserved layout slot for the future carVertical affiliate widget (see
 * docs/MONETIZATION_SPEC.md). VIN extraction isn't wired up yet, so this is
 * a placeholder — no affiliate link, no tracking — just holding the spot
 * next to the PPMV result so the real widget can drop in later. */
export function CarVerticalCard() {
  return (
    <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-alt)] px-5 py-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-[var(--text)]">Provjeri povijest vozila</p>
          <p className="text-xs text-[var(--text-soft)] mt-0.5">
            Kilometraža, štete i vlasništvo putem carVertical — uskoro dostupno.
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-[var(--border)] px-2.5 py-1 text-[10px] font-medium text-[var(--text-soft)]">
          Uskoro
        </span>
      </div>
    </div>
  );
}
