"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { searchWikipediaEngines } from "@/lib/api";
import { WikipediaEngineRow } from "@/lib/types";

interface Props {
  onClose: () => void;
  /** Called with the row the user picked. The caller applies its CO2. */
  onSelect: (row: WikipediaEngineRow) => void;
  brand: string;
  /** Initial search text — model + engine designation from the listing, so the
   * list opens already narrowed to roughly the right car. */
  initialQuery: string;
}

export function co2Of(row: WikipediaEngineRow): number | null {
  if (row.co2_min === null && row.co2_max === null) return null;
  if (row.co2_min === null) return row.co2_max;
  if (row.co2_max === null) return row.co2_min;
  // A stored range is the spread across a variant's production run. Once the
  // user has told us which variant it is, the midpoint is the least-wrong
  // single number to seed the field with — and it stays editable.
  return Math.round((row.co2_min + row.co2_max) / 2);
}

export function formatCo2(row: WikipediaEngineRow): string {
  if (row.co2_min === null && row.co2_max === null) return "—";
  if (row.co2_min !== null && row.co2_max !== null && row.co2_min !== row.co2_max) {
    return `${row.co2_min}–${row.co2_max}`;
  }
  return String(row.co2_min ?? row.co2_max);
}

function formatPeriod(row: WikipediaEngineRow): string {
  if (!row.production_start && !row.production_end) return "";
  return `${row.production_start ?? "?"}–${row.production_end ?? ""}`.replace(/–$/, "–");
}

/** Pick the engine variant, and take its CO2.
 *
 * Exists because the stored data is often unambiguous while the *listing* is
 * not. The Audi A2 is the case in point: Wikipedia has all five variants
 * separately, but autobid.de publishes no fuel type, so a 55 kW "A2 1.4" ties
 * the petrol 1.4 (142 g/km) against the diesel 1.4 TDI (116 g/km) and the
 * matcher can only report their union, 116–142. No tuning fixes that — the
 * owner knows which one they bought, so they choose.
 *
 * Selecting is a deliberate act, which is what makes filling the CO2 field
 * here compatible with the plan's rule against *auto*-filling. */
export function Co2EnginesModal({ onClose, onSelect, brand, initialQuery }: Props) {
  const [query, setQuery] = useState(initialQuery);
  const [rows, setRows] = useState<WikipediaEngineRow[] | null>(null);
  const [brandKnown, setBrandKnown] = useState(true);
  // Starts true because this always fetches on mount.
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const fetchRows = useCallback(
    async (q: string) => {
      try {
        const data = await searchWikipediaEngines({ brand, q: q.trim() || undefined });
        setRows(data.rows);
        setBrandKnown(data.brand_known);
        setError(null);
      } catch {
        setError("Dohvat podataka nije uspio. Pokušajte ponovno.");
        setRows([]);
      } finally {
        setLoading(false);
      }
    },
    [brand],
  );

  const run = useCallback(
    (q: string) => {
      setLoading(true);
      void fetchRows(q);
    },
    [fetchRows],
  );

  // Search once on mount, so opening shows results rather than an empty box.
  //
  // set-state-in-effect fires here because it traces into fetchRows and finds
  // the setState calls that store the response. Fetching on mount is the
  // legitimate case the rule can't distinguish: the state isn't derivable
  // during render, and the mount *is* the trigger. fetchRows writes nothing
  // before its first await, so there is no synchronous cascade.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchRows(initialQuery);
    inputRef.current?.focus();
  }, [initialQuery, fetchRows]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Odabir motora"
        onClick={(e) => e.stopPropagation()}
        className="w-full sm:max-w-xl max-h-[85vh] flex flex-col rounded-t-2xl sm:rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-lg overflow-hidden"
      >
        <div className="px-4 py-2.5 border-b border-[var(--border)] bg-[var(--surface-alt)] flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[var(--text)]">
              Odaberite motor — {brand}
            </h3>
            <p className="text-xs text-[var(--text-soft)]">
              Podaci s Wikipedije, nisu službeni. Odabir upisuje CO2 u obrazac.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Zatvori"
            className="shrink-0 rounded-lg px-2 py-1 text-sm text-[var(--text-soft)] hover:bg-[var(--surface)]"
          >
            ✕
          </button>
        </div>

        <div className="px-4 py-2.5 border-b border-[var(--border)]">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              run(query);
            }}
            className="flex gap-2"
          >
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="npr. 1.4 TDI ili 320d"
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-1.5 text-sm text-[var(--text)] focus:border-[var(--primary)] transition-colors"
            />
            <button
              type="submit"
              className="shrink-0 rounded-xl bg-[var(--primary)] px-4 py-1.5 text-sm font-medium text-white"
            >
              Traži
            </button>
          </form>
        </div>

        <div className="overflow-y-auto">
          {loading && <p className="px-4 py-6 text-sm text-[var(--text-soft)]">Učitavanje…</p>}

          {!loading && error && <p className="px-4 py-6 text-sm text-[var(--err)]">{error}</p>}

          {!loading && !error && rows !== null && rows.length === 0 && (
            <p className="px-4 py-6 text-sm text-[var(--text-soft)]">
              {brandKnown
                ? "Nema rezultata. Pokušajte kraći pojam, npr. samo oznaku motora."
                : `Za marku ${brand} nemamo podataka s Wikipedije.`}
            </p>
          )}

          {!loading && !error && rows !== null && rows.length > 0 && (
            <ul className="divide-y divide-[var(--border)]">
              {rows.map((row, i) => (
                <li key={`${row.source_url}-${row.engine_code ?? "x"}-${row.power_kw ?? "x"}-${i}`}>
                  <button
                    type="button"
                    onClick={() => onSelect(row)}
                    className="w-full text-left px-4 py-2 flex items-center justify-between gap-3 hover:bg-[var(--surface-alt)] transition-colors"
                  >
                    <span className="min-w-0 text-xs text-[var(--text-soft)] truncate">
                      <span className="text-sm font-medium text-[var(--text)]">
                        {row.engine_code ?? "—"}
                      </span>
                      {"  "}
                      {row.power_kw ? `${row.power_kw} kW` : ""}
                      {row.fuel_type ? ` · ${row.fuel_type}` : ""}
                      {formatPeriod(row) ? ` · ${formatPeriod(row)}` : ""}
                      {` · ${row.model_article_title}`}
                    </span>
                    <span className="font-mono-tab text-sm text-[var(--text)] shrink-0">
                      {formatCo2(row)}
                      <span className="text-xs text-[var(--text-soft)]"> g/km</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
