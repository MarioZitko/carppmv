"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getWikipediaBrands,
  searchWikipediaEngines,
  searchWikipediaModels,
} from "@/lib/api";
import { WikipediaEngineRow, WikipediaModelRow } from "@/lib/types";

interface Props {
  onClose: () => void;
  /** Called with the row the user picked, and the marque it was browsed under
   * — the row itself carries no brand, and after the brand step that marque is
   * no longer something the caller can assume it knows. */
  onSelect: (row: WikipediaEngineRow, brand: string) => void;
  /** Marque from the listing or the picked catalogue row, when there is one.
   * Null opens the picker at the brand list instead — the case that makes this
   * usable on an untouched form, with no URL pasted and nothing parsed. */
  brand?: string | null;
  /** Initial search text — model + engine designation from the listing. Used to
   * *rank* the model list, never to skip past it. Only ever seeds the brand it
   * came with; it is meaningless under any other marque. */
  initialQuery?: string;
  /** Model article the user already drilled into, so reopening the picker
   * resumes there instead of dropping back to the brand list. Requires
   * `brand`; ignored without one. */
  initialArticle?: string | null;
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

/** Pick the engine variant, and take its CO2 — in three steps: which marque,
 * which model, then which engine.
 *
 * **Why steps and not one search box.** Free-text matching over a listing blob
 * cannot always be trusted to have found the right car, and nothing in its
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
 * **The brand step is what makes this a browser rather than a follow-up to a
 * scrape.** It is the entry point whenever no listing supplied a marque, so a
 * user who never pastes a URL — typing their car's figures in by hand, which is
 * a first-class path through this form — can still reach the corpus. When a
 * marque *was* supplied the picker opens past it, but the crumb back to the
 * full list stays live: a scrape that read the wrong brand, or a user checking
 * a different car, must not be a dead end.
 *
 * Selecting is a deliberate act, which is what makes filling the CO2 field here
 * compatible with the plan's rule against *auto*-filling. */
export function Co2EnginesModal({
  onClose,
  onSelect,
  brand: initialBrand,
  initialQuery = "",
  initialArticle,
  registered,
}: Props) {
  // Brand and article together are the whole navigation state: no brand is step
  // zero, brand without article is step one.
  const [brand, setBrand] = useState<string | null>(initialBrand ?? null);
  // Only the article *title* — that is all the fetches and the breadcrumb need,
  // and keeping it a string is what lets a caller restore this step from the
  // engine row it holds, which carries a title and not a model row.
  const [article, setArticle] = useState<string | null>(
    initialBrand ? (initialArticle ?? null) : null,
  );
  const [query, setQuery] = useState(
    initialBrand && !initialArticle ? initialQuery : "",
  );

  const [brands, setBrands] = useState<string[] | null>(null);
  const [models, setModels] = useState<WikipediaModelRow[] | null>(null);
  const [rows, setRows] = useState<WikipediaEngineRow[] | null>(null);
  const [brandKnown, setBrandKnown] = useState(true);
  const [ignored, setIgnored] = useState<string[]>([]);
  // The registration date narrows both list steps, and a listing's parsed date
  // is not always right. Scoping silently would rebuild the trap this whole
  // rework is meant to remove — a user whose date is wrong by a year would see
  // a list with their car missing and no way to tell why. So it is visible and
  // switchable, and the user's own choice wins over the parse.
  const [dateScoped, setDateScoped] = useState(true);
  const scope = dateScoped ? registered : null;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  /** The listing text ranks the marque it was read from and nothing else — as a
   * query under another brand it is pure noise, and worse than noise on the
   * model step, where every word it drops is reported to the user. */
  const seedQuery = useCallback(
    (target: string) => (initialBrand && target === initialBrand ? initialQuery : ""),
    [initialBrand, initialQuery],
  );

  const loadBrands = useCallback(async () => {
    try {
      const list = await getWikipediaBrands();
      setBrands(list);
      setError(null);
    } catch {
      setError("Dohvat popisa marki nije uspio. Pokušajte ponovno.");
      setBrands([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Brand is passed in rather than closed over, so these callbacks depend only
  // on `scope`. Closing over the brand state would make every navigation
  // rebuild them, and the mount effect below would fire again on each one.
  const fetchModels = useCallback(
    async (target: string, q: string) => {
      try {
        const data = await searchWikipediaModels({
          brand: target,
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
    [scope],
  );

  const fetchEngines = useCallback(
    async (target: string, q: string, title: string) => {
      try {
        const data = await searchWikipediaEngines({
          brand: target,
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
    [scope],
  );

  // Load the step we open on, so opening shows a list rather than an empty box.
  //
  // Mount-only on purpose, and the deps array says so: `fetchModels` and
  // `loadBrands` are listed by the exhaustive-deps rule, but `fetchModels`
  // changes identity whenever the date scope is toggled, and re-running this
  // effect then would refetch the *opening* step's list — models, with the
  // listing query — on top of whatever step the user has since navigated to.
  // The scope effect below is what handles that change, for the current step.
  //
  // set-state-in-effect fires here because it traces into the fetchers and
  // finds the setState calls that store the response. Fetching on mount is the
  // legitimate case that rule can't distinguish: the state isn't derivable
  // during render, and the mount *is* the trigger.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- see above: the opening
       list has to be fetched, and its arrival is state. */
    if (initialBrand && initialArticle) {
      void fetchEngines(initialBrand, "", initialArticle);
    } else if (initialBrand) {
      void fetchModels(initialBrand, initialQuery);
    } else {
      void loadBrands();
    }
    /* eslint-enable react-hooks/set-state-in-effect */
    // Autofocus only where focusing does not raise a keyboard. The signal is
    // the pointer, not the viewport width: a tablet is wide *and* touch, so a
    // width check would still pop the keyboard and shove a centred dialog
    // behind it. On touch the user taps the field when they want it.
    const coarse = window.matchMedia?.("(pointer: coarse)").matches ?? false;
    if (!coarse) inputRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function chooseBrand(target: string) {
    const seed = seedQuery(target);
    setBrand(target);
    setArticle(null);
    setModels(null);
    setQuery(seed);
    setLoading(true);
    void fetchModels(target, seed);
  }

  function chooseModel(model: WikipediaModelRow) {
    setArticle(model.model_article_title);
    setRows(null);
    // The listing text got us to the right generation; inside it, it is mostly
    // noise. Starting the engine step blank shows every variant, which is the
    // shorter and more reliable list to scan.
    setQuery("");
    setLoading(true);
    void fetchEngines(brand!, "", model.model_article_title);
  }

  function backToModels() {
    if (!brand) return;
    const seed = seedQuery(brand);
    setArticle(null);
    setRows(null);
    setQuery(seed);
    setLoading(true);
    void fetchModels(brand, seed);
  }

  function backToBrands() {
    setBrand(null);
    setArticle(null);
    setModels(null);
    setRows(null);
    setQuery("");
    setIgnored([]);
    setError(null);
    // The list is short and never changes mid-session, so a second visit is
    // instant rather than another round trip.
    if (brands === null) {
      setLoading(true);
      void loadBrands();
    } else {
      setLoading(false);
    }
  }

  function runSearch(q: string) {
    // The brand list filters as you type — there is nothing to submit.
    if (!brand) return;
    setLoading(true);
    if (article) void fetchEngines(brand, q, article);
    else void fetchModels(brand, q);
  }

  // fetchModels/fetchEngines close over `scope`, so the refetch has to wait for
  // the re-render that the toggle causes rather than firing inside it.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (!brand) return;
    /* eslint-disable react-hooks/set-state-in-effect -- refetching the current
       step is exactly what this effect is for; the spinner and the response
       both have to land as state. */
    setLoading(true);
    if (article) void fetchEngines(brand, query, article);
    else void fetchModels(brand, query);
    /* eslint-enable react-hooks/set-state-in-effect */
    // Only the scope change should retrigger this; query, brand and article
    // changes already refetch through their own handlers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateScoped]);

  const step = !brand ? "brand" : article ? "engine" : "model";

  // Filtered in the browser rather than on the server: it is one short list
  // (37 marques) that never changes, so a round trip per keystroke would buy
  // nothing but latency.
  const brandFilter = query.trim().toLowerCase();
  const shownBrands = (brands ?? []).filter(
    (b) => !brandFilter || b.toLowerCase().includes(brandFilter),
  );

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
              article={article}
              onBrands={backToBrands}
              onBrand={backToModels}
            />
            <p className="mt-0.5 text-xs text-[var(--text-soft)]">
              {step === "brand"
                ? "Odaberite marku vozila. Podaci s Wikipedije, nisu službeni."
                : step === "model"
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
                step === "brand"
                  ? "npr. BMW ili Volkswagen"
                  : step === "model"
                    ? "npr. Golf ili 320d"
                    : "npr. 1.4 TDI ili 320d"
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
            {/* No submit on the brand step: that list filters as you type, and
                a button that visibly does nothing reads as a broken one. */}
            {step !== "brand" && (
              <button
                type="submit"
                className="shrink-0 rounded-xl bg-[var(--primary)] px-4 py-1.5 text-sm font-medium text-white"
              >
                Traži
              </button>
            )}
          </form>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {registered && step !== "brand" && (
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
            {step !== "brand" && <IgnoredTerms terms={ignored} step={step} />}
          </div>
        </div>

        <div className="overflow-y-auto">
          {loading && <p className="px-4 py-6 text-sm text-[var(--text-soft)]">Učitavanje…</p>}

          {!loading && error && <p className="px-4 py-6 text-sm text-[var(--err)]">{error}</p>}

          {!loading && !error && step === "brand" && brands !== null && (
            shownBrands.length === 0 ? (
              <p className="px-4 py-6 text-sm text-[var(--text-soft)]">
                Nema marke koja odgovara pojmu „{query.trim()}”.
              </p>
            ) : (
              /* A grid, not the rows the other two steps use: these are 37
                 short labels with nothing to say about themselves, so a
                 one-per-row list would be three screens of mostly whitespace. */
              <ul className="grid grid-cols-2 sm:grid-cols-3 gap-2 p-4">
                {shownBrands.map((b) => (
                  <li key={b}>
                    <button
                      type="button"
                      onClick={() => chooseBrand(b)}
                      className="w-full min-h-[44px] rounded-xl border border-[var(--border)] px-3 py-2 text-sm font-medium text-[var(--text)] text-left hover:border-[var(--primary)] hover:bg-[var(--surface-alt)] hover:text-[var(--primary)] transition-colors"
                    >
                      {b}
                    </button>
                  </li>
                ))}
              </ul>
            )
          )}

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
                      onClick={() => onSelect(row, brand!)}
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
 * Each ancestor crumb is a real button rather than a decorative label: on a
 * phone it is the only way back a step, and burying that behind the browser's
 * back gesture (which would close the page, not the step) is how a multi-step
 * modal becomes a trap. That includes the brand crumb on the model step even
 * when the caller supplied the brand — a scrape that read the wrong marque
 * would otherwise strand the user on the wrong list.
 *
 * It stays on one line at every width — the article title truncates rather than
 * wrapping the crumb trail onto a second row, because the header is a fixed
 * block above a scrolling list and a second row there eats list space on the
 * smallest screens. For the same reason the engine step shows only its parent
 * model, not the full marque/model/engine trail. */
function Breadcrumbs({
  brand,
  article,
  onBrands,
  onBrand,
}: {
  brand: string | null;
  article: string | null;
  onBrands: () => void;
  onBrand: () => void;
}) {
  if (!brand) {
    return (
      <h3 className="text-sm font-semibold text-[var(--text)] truncate">
        Odaberite marku vozila
      </h3>
    );
  }
  const [parentLabel, onParent, current] = article
    ? ([brand, onBrand, article] as const)
    : (["Sve marke", onBrands, brand] as const);
  return (
    <h3 className="flex items-center gap-1 text-sm min-w-0">
      <button
        type="button"
        onClick={onParent}
        className="shrink-0 flex items-center gap-1 -ml-1 px-1 py-0.5 rounded font-medium text-[var(--primary)] hover:bg-[var(--primary-soft)] transition-colors"
      >
        <ChevronLeft />
        {parentLabel}
      </button>
      <span aria-hidden className="shrink-0 text-[var(--text-soft)]">
        /
      </span>
      <span className="min-w-0 truncate font-semibold text-[var(--text)]">
        {current}
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
