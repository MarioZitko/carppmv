"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { searchWikipediaEngines, searchWikipediaModels } from "@/lib/api";
import { WikipediaEngineRow, WikipediaModelRow } from "@/lib/types";

interface Props {
  onClose: () => void;
  /** Called with the row the user picked. The caller applies its CO2. */
  onSelect: (row: WikipediaEngineRow) => void;
  brand: string;
  /** Initial search text — model + engine designation from the listing. Used to
   * *rank* the model list, never to skip past it. */
  initialQuery: string;
  /** ISO first-registration date, when the form has one. Scopes both steps to
   * generations that could plausibly have been registered then. */
  registered?: string | null;
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

export function formatCo2(row: { co2_min: number | null; co2_max: number | null }): string {
  if (row.co2_min === null && row.co2_max === null) return "—";
  if (row.co2_min !== null && row.co2_max !== null && row.co2_min !== row.co2_max) {
    return `${row.co2_min}–${row.co2_max}`;
  }
  return String(row.co2_min ?? row.co2_max);
}

function formatPeriod(row: { production_start: string | null; production_end: string | null }): string {
  if (!row.production_start && !row.production_end) return "";
  const from = row.production_start ?? "?";
  // A generation with no end is current, not unknown — say so rather than
  // trailing an en dash into nothing.
  return row.production_end ? `${from}–${row.production_end}` : `${from}–danas`;
}

/** Pick the engine variant, and take its CO2 — in two steps: which model, then
 * which engine.
 *
 * **Why two steps and not one search box.** Free-text matching over a listing
 * blob cannot always be trusted to have found the right car, and nothing in its
 * result says when it hasn't. A 3-series Gran Turismo has no de.wikipedia
 * article at all, so the closest honest answer is a different body of the same
 * era — offered with no visible difference from a correct one. Only the person
 * holding the logbook can tell. Choosing the generation first takes the guess
 * out of the step that matters and leaves the text box the job the corpus does
 * reliably: telling engines apart inside one generation.
 *
 * The same logic covers the ambiguity this picker was originally built for. The
 * Audi A2's 55 kW petrol 1.4 (142 g/km) and 55 kW diesel 1.4 TDI (116 g/km) are
 * indistinguishable to the matcher because autobid.de publishes no fuel type,
 * so it can only report their union, 116–142. The owner knows which they bought.
 *
 * Selecting is a deliberate act, which is what makes filling the CO2 field here
 * compatible with the plan's rule against *auto*-filling. */
export function Co2EnginesModal({
  onClose,
  onSelect,
  brand,
  initialQuery,
  registered,
}: Props) {
  // The chosen article is the whole navigation state: null is step one.
  const [article, setArticle] = useState<WikipediaModelRow | null>(null);
  const [query, setQuery] = useState(initialQuery);

  const [models, setModels] = useState<WikipediaModelRow[] | null>(null);
  const [rows, setRows] = useState<WikipediaEngineRow[] | null>(null);
  const [brandKnown, setBrandKnown] = useState(true);
  const [ignored, setIgnored] = useState<string[]>([]);
  // The registration date narrows both steps, and a listing's parsed date is
  // not always right. Scoping silently would rebuild the trap this whole
  // rework is meant to remove — a user whose date is wrong by a year would see
  // a list with their car missing and no way to tell why. So it is visible and
  // switchable, and the user's own choice wins over the parse.
  const [dateScoped, setDateScoped] = useState(true);
  const scope = dateScoped ? registered : null;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const fetchModels = useCallback(
    async (q: string) => {
      try {
        const data = await searchWikipediaModels({
          brand,
          q: q.trim() || undefined,
          registered: scope,
        });
        setModels(data.models);
        setBrandKnown(data.brand_known);
        setIgnored(data.ignored_terms ?? []);
        setError(null);
      } catch {
        setError("Dohvat podataka nije uspio. Pokušajte ponovno.");
        setModels([]);
        setIgnored([]);
      } finally {
        setLoading(false);
      }
    },
    [brand, scope],
  );

  const fetchEngines = useCallback(
    async (q: string, title: string) => {
      try {
        const data = await searchWikipediaEngines({
          brand,
          q: q.trim() || undefined,
          article: title,
          registered: scope,
        });
        setRows(data.rows);
        setIgnored(data.ignored_terms ?? []);
        setError(null);
      } catch {
        setError("Dohvat podataka nije uspio. Pokušajte ponovno.");
        setRows([]);
        setIgnored([]);
      } finally {
        setLoading(false);
      }
    },
    [brand, scope],
  );

  // Search once on mount, so opening shows models rather than an empty box.
  //
  // set-state-in-effect fires here because it traces into fetchModels and finds
  // the setState calls that store the response. Fetching on mount is the
  // legitimate case the rule can't distinguish: the state isn't derivable
  // during render, and the mount *is* the trigger.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchModels(initialQuery);
    // Autofocus only where focusing does not raise a keyboard. The signal is
    // the pointer, not the viewport width: a tablet is wide *and* touch, so a
    // width check would still pop the keyboard and shove a centred dialog
    // behind it. On touch the user taps the field when they want it.
    const coarse = window.matchMedia?.("(pointer: coarse)").matches ?? false;
    if (!coarse) inputRef.current?.focus();
  }, [initialQuery, fetchModels]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function chooseModel(model: WikipediaModelRow) {
    setArticle(model);
    setRows(null);
    // The listing text got us to the right generation; inside it, it is mostly
    // noise. Starting the engine step blank shows every variant, which is the
    // shorter and more reliable list to scan.
    setQuery("");
    setLoading(true);
    void fetchEngines("", model.model_article_title);
  }

  function backToModels() {
    setArticle(null);
    setRows(null);
    setQuery(initialQuery);
    setLoading(true);
    void fetchModels(initialQuery);
  }

  function runSearch(q: string) {
    setLoading(true);
    if (article) void fetchEngines(q, article.model_article_title);
    else void fetchModels(q);
  }

  // fetchModels/fetchEngines close over `scope`, so the refetch has to wait for
  // the re-render that the toggle causes rather than firing inside it.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setLoading(true);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (article) void fetchEngines(query, article.model_article_title);
    else void fetchModels(query);
    // Only the scope change should retrigger this; query and article changes
    // already refetch through their own handlers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateScoped]);

  const step = article ? "engine" : "model";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Odabir motora"
        onClick={(e) => e.stopPropagation()}
        className="w-full sm:max-w-xl max-h-[85dvh] flex flex-col rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-lg overflow-hidden"
      >
        <div className="px-4 py-2.5 border-b border-[var(--border)] bg-[var(--surface-alt)] flex items-start justify-between gap-3">
          <div className="min-w-0">
            <Breadcrumbs
              brand={brand}
              article={article?.model_article_title ?? null}
              onBrand={backToModels}
            />
            <p className="mt-0.5 text-xs text-[var(--text-soft)]">
              {step === "model"
                ? "Odaberite model vozila. Podaci s Wikipedije, nisu službeni."
                : "Odaberite motor. Odabir upisuje CO2 u obrazac."}
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
              runSearch(query);
            }}
            className="flex gap-2"
          >
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={
                step === "model" ? "npr. Golf ili 320d" : "npr. 1.4 TDI ili 320d"
              }
              className="w-full min-w-0 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-1.5 text-sm text-[var(--text)] focus:border-[var(--primary)] transition-colors"
            />
            {query && (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  runSearch("");
                }}
                className="shrink-0 rounded-xl border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--text-soft)] hover:text-[var(--text)] transition-colors"
              >
                Sve
              </button>
            )}
            <button
              type="submit"
              className="shrink-0 rounded-xl bg-[var(--primary)] px-4 py-1.5 text-sm font-medium text-white"
            >
              Traži
            </button>
          </form>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {registered && (
              <button
                type="button"
                onClick={() => setDateScoped((v) => !v)}
                className={`mt-1.5 shrink-0 rounded-full border px-2 py-0.5 text-xs transition-colors ${
                  dateScoped
                    ? "border-[var(--primary)] bg-[var(--primary-soft)] text-[var(--primary)]"
                    : "border-[var(--border)] text-[var(--text-soft)] hover:text-[var(--text)]"
                }`}
              >
                {dateScoped
                  ? `godište ${registered.slice(0, 4)} ✕`
                  : "sva godišta"}
              </button>
            )}
            <IgnoredTerms terms={ignored} step={step} />
          </div>
        </div>

        <div className="overflow-y-auto">
          {loading && <p className="px-4 py-6 text-sm text-[var(--text-soft)]">Učitavanje…</p>}

          {!loading && error && <p className="px-4 py-6 text-sm text-[var(--err)]">{error}</p>}

          {!loading && !error && step === "model" && models !== null && (
            models.length === 0 ? (
              <p className="px-4 py-6 text-sm text-[var(--text-soft)]">
                {brandKnown
                  ? "Nema modela za zadani datum registracije."
                  : `Za marku ${brand} nemamo podataka s Wikipedije.`}
              </p>
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {models.map((model) => (
                  <li key={model.model_article_title}>
                    <button
                      type="button"
                      onClick={() => chooseModel(model)}
                      className="w-full text-left px-4 py-2.5 min-h-[44px] flex items-center justify-between gap-3 hover:bg-[var(--surface-alt)] transition-colors"
                    >
                      <span className="min-w-0">
                        <span className="block text-sm font-medium text-[var(--text)] truncate">
                          {model.model_article_title}
                          <span className="ml-1.5 font-normal text-xs text-[var(--text-soft)]">
                            {formatPeriod(model)}
                          </span>
                        </span>
                        {/* Chassis codes mean nothing to most people; the
                            badges inside the generation are what they know. */}
                        <span className="block text-xs text-[var(--text-soft)] truncate">
                          {model.sample_engine_codes.join(" · ")}
                          {model.variant_count > model.sample_engine_codes.length &&
                            ` · +${model.variant_count - model.sample_engine_codes.length}`}
                        </span>
                      </span>
                      <ChevronRight />
                    </button>
                  </li>
                ))}
              </ul>
            )
          )}

          {!loading && !error && step === "engine" && rows !== null && (
            rows.length === 0 ? (
              <p className="px-4 py-6 text-sm text-[var(--text-soft)]">
                Nema rezultata unutar ovog modela. Obrišite pojam za cijeli popis.
              </p>
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {rows.map((row, i) => (
                  <li key={`${row.source_url}-${row.engine_code ?? "x"}-${row.power_kw ?? "x"}-${i}`}>
                    <button
                      type="button"
                      onClick={() => onSelect(row)}
                      className="w-full text-left px-4 py-2 min-h-[44px] flex items-center justify-between gap-3 hover:bg-[var(--surface-alt)] transition-colors"
                    >
                      <span className="min-w-0 text-xs text-[var(--text-soft)] truncate">
                        <span className="text-sm font-medium text-[var(--text)]">
                          {row.engine_code ?? "—"}
                        </span>
                        {"  "}
                        {row.power_kw ? `${row.power_kw} kW` : ""}
                        {row.fuel_type ? ` · ${row.fuel_type}` : ""}
                        {formatPeriod(row) ? ` · ${formatPeriod(row)}` : ""}
                      </span>
                      <span className="font-mono-tab text-sm text-[var(--text)] shrink-0">
                        {formatCo2(row)}
                        <span className="text-xs text-[var(--text-soft)]"> g/km</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )
          )}
        </div>
      </div>
    </div>
  );
}

/** Where you are, and the way back.
 *
 * The brand crumb is a real button rather than a decorative label: on a phone
 * it is the only way back to the model list, and burying that behind the
 * browser's back gesture (which would close the page, not the step) is how a
 * two-step modal becomes a trap. It stays on one line at every width — the
 * article title truncates rather than wrapping the crumb trail onto a second
 * row, because the header is a fixed block above a scrolling list and a second
 * row there eats list space on the smallest screens. */
function Breadcrumbs({
  brand,
  article,
  onBrand,
}: {
  brand: string;
  article: string | null;
  onBrand: () => void;
}) {
  if (!article) {
    return (
      <h3 className="text-sm font-semibold text-[var(--text)] truncate">
        Odaberite model — {brand}
      </h3>
    );
  }
  return (
    <h3 className="flex items-center gap-1 text-sm min-w-0">
      <button
        type="button"
        onClick={onBrand}
        className="shrink-0 flex items-center gap-1 -ml-1 px-1 py-0.5 rounded font-medium text-[var(--primary)] hover:bg-[var(--primary-soft)] transition-colors"
      >
        <ChevronLeft />
        {brand}
      </button>
      <span aria-hidden className="shrink-0 text-[var(--text-soft)]">
        /
      </span>
      <span className="min-w-0 truncate font-semibold text-[var(--text)]">
        {article}
      </span>
    </h3>
  );
}

/** The words the search could not honour.
 *
 * Not decoration: best-coverage ranking always returns something when any word
 * matches, so an engine list can be offered for a car the corpus does not hold.
 * A 3-series Gran Turismo is the standing case — no F34 article exists, "GT"
 * matches nothing, and what comes back is a different body of the same era.
 *
 * On the model step it reads differently and the wording says so: nothing is
 * hidden there, so an ignored word only explains the ordering.
 *
 * Capped to one truncating line with a +N overflow, in the modal's fixed header
 * rather than above the scrolling list, so a noisy listing title that drops six
 * words cannot push the rows around. The full list is in the title attribute. */
function IgnoredTerms({ terms, step }: { terms: string[]; step: "model" | "engine" }) {
  if (!terms.length) return null;
  const MAX = 4;
  const shown = terms.slice(0, MAX);
  const rest = terms.length - shown.length;
  return (
    <p
      title={`Nije pronađeno: ${terms.join(", ")}`}
      className="mt-1.5 text-xs text-[var(--text-soft)] truncate"
    >
      {step === "model" ? "Ne utječe na popis:" : "Zanemareno:"}{" "}
      <span className="capitalize text-[var(--text)]">{shown.join(", ")}</span>
      {rest > 0 && ` +${rest}`}
    </p>
  );
}

function ChevronRight() {
  return (
    <svg
      width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="shrink-0 text-[var(--text-soft)]"
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

function ChevronLeft() {
  return (
    <svg
      width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
      className="shrink-0"
    >
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}
