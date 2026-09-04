"use client";

import { useEffect, useRef, useState } from "react";
import { WikipediaCo2Hint } from "@/lib/types";

/** Roughly the panel's own height plus breathing room. Only decides which way
 * it opens, so being approximate costs nothing. */
const POPOVER_HEIGHT_ALLOWANCE = 200;

interface Props {
  hint: WikipediaCo2Hint | null | undefined;
  /** Engine designation, shown once the user has picked a variant themselves —
   * it's the thing they chose, so it's more use than the article title. */
  engineCode?: string | null;
  /** Opens the engine picker. Omitted when the listing gave us no brand. */
  onBrowse?: () => void;
  /** True once the user picked a range-valued variant, so the CO2 field holds
   * that range's midpoint rather than a stated figure. */
  midpointApplied?: boolean;
}

/** The last-resort CO2 estimate, rendered *inside* the CO2 field.
 *
 * Deliberately NOT styled like CandidatesList — that component's score badge
 * uses the ok/warn/err palette and a match percentage, which read as "the
 * system is confident, accept this." This tier is the opposite claim: it
 * answers for ~36% of vehicles and only ~55% of those answers contain the true
 * value. So the treatment is muted surface, no status color, no score.
 *
 * **It lives in the field's own box, and its detail is a popover, because an
 * earlier version was a block below the input.** That block sat in one cell of
 * a three-column grid and stretched the whole row, shoving the date fields
 * down the page — it read as a box someone had inserted into the form rather
 * than part of it. Everything here is either inside the input's trailing edge
 * or absolutely positioned, so the grid row keeps exactly the height a bare
 * input gives it and nothing below moves.
 *
 * Display only. It never writes to the CO2 field — not on load, and not behind
 * a button. A value this uncertain reaching the tax base is what
 * docs/WIKIPEDIA_CO2_PLAN.md §0 forbids, and the field stays the user's to
 * fill. Only an explicit pick in the engine picker fills it. */
export function Co2HintNote({ hint, engineCode, onBrowse, midpointApplied }: Props) {
  const [open, setOpen] = useState(false);
  // Which way the detail opens. Down is right almost always; the exception is
  // the CO2 field sitting at the foot of a short mobile viewport, where a
  // downward panel lands below the fold. Nothing clips it there — it is in
  // flow and a scroll reaches it — but making the user scroll to read a panel
  // they just opened is a bad answer when flipping it is a class name.
  const [dropUp, setDropUp] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const chipRef = useRef<HTMLButtonElement>(null);

  function toggle() {
    setOpen((wasOpen) => {
      if (!wasOpen) {
        const rect = chipRef.current?.getBoundingClientRect();
        setDropUp(
          !!rect && window.innerHeight - rect.bottom < POPOVER_HEIGHT_ALLOWANCE,
        );
      }
      return !wasOpen;
    });
  }

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onDown(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  // No estimate, but a brand we can browse: the same slot becomes the way in
  // to the picker. Previously a separate line of link text under the field —
  // which is exactly the kind of thing that was stretching the grid row.
  if (!hint) {
    if (!onBrowse) return null;
    return (
      <button
        type="button"
        onClick={onBrowse}
        title="Potražite motor u bazi s Wikipedije"
        className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-2 py-1 text-[11px] font-medium text-[var(--text-soft)] hover:text-[var(--primary)] hover:border-[var(--primary)] transition-colors"
      >
        <SearchIcon />
        Wikipedia
      </button>
    );
  }

  const range =
    hint.co2_min_g_km === hint.co2_max_g_km
      ? `${hint.co2_min_g_km}`
      : `${hint.co2_min_g_km}–${hint.co2_max_g_km}`;

  return (
    <div ref={wrapRef}>
      <button
        ref={chipRef}
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls="co2-hint-detail"
        title="Procjena s Wikipedije — kliknite za detalje"
        className={`absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors ${
          open
            ? "border-[var(--primary)] bg-[var(--primary-soft)] text-[var(--primary)]"
            : "border-[var(--border)] bg-[var(--surface-alt)] text-[var(--text-soft)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
        }`}
      >
        <span className="font-mono-tab">≈ {range}</span>
        <ChevronIcon open={open} />
      </button>

      {open && (
        <div
          id="co2-hint-detail"
          // Absolutely positioned so it costs the grid row no height at all —
          // the whole point of the rework. z-30 clears the sticky header (10)
          // and the mobile price bar (20).
          className={`absolute right-0 z-30 w-72 min-w-full max-w-[calc(100vw-2rem)] rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-lg overflow-hidden ${
            dropUp ? "bottom-full mb-1.5" : "top-full mt-1.5"
          }`}
        >
          <div className="px-3 py-2.5 bg-[var(--surface-alt)]">
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase tracking-wide font-medium text-[var(--text-soft)] border border-[var(--border)] rounded-full px-1.5 py-0.5">
                procjena
              </span>
              <span className="text-xs text-[var(--text-soft)] whitespace-nowrap">
                Wikipedia:{" "}
                <span className="font-mono-tab text-[var(--text)]">{range} g/km</span>
              </span>
            </div>
            <p className="mt-1.5 text-xs leading-snug text-[var(--text-soft)]">
              {midpointApplied
                ? "Upisana je sredina raspona — prilagodite ako znate točnu vrijednost."
                : "Nije službeni podatak. Provjerite COC dokument vozila i upišite točnu vrijednost."}
            </p>
          </div>

          {onBrowse && (
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onBrowse();
              }}
              className="w-full min-h-[44px] flex items-center gap-2 px-3 text-sm font-medium text-[var(--primary)] bg-[var(--primary-soft)] hover:brightness-95 transition-all"
            >
              <ListIcon />
              Promijeni motor
            </button>
          )}

          {/* The other action leaves the app entirely, so it is deliberately
              not a second line of the same blue link text: different weight,
              different colour, its own row below a divider, and an
              external-link glyph rather than the in-app list glyph above. */}
          <a
            href={hint.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="min-h-[44px] flex items-center justify-between gap-2 px-3 border-t border-[var(--border)] text-xs text-[var(--text-soft)] hover:text-[var(--text)] hover:bg-[var(--surface-alt)] transition-colors"
          >
            <span className="min-w-0 truncate">
              Izvor: {engineCode ?? hint.model_article_title}
            </span>
            <ExternalIcon />
          </a>
        </div>
      )}
    </div>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="10" height="10" viewBox="0 0 24 24" fill="none" aria-hidden
      stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"
      className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      width="11" height="11" viewBox="0 0 24 24" fill="none" aria-hidden
      stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
      className="shrink-0"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </svg>
  );
}

/** In-app affordance: a list to pick from, opening here. */
function ListIcon() {
  return (
    <svg
      width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="shrink-0"
    >
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </svg>
  );
}

/** Leaves the app: the standard box-with-outgoing-arrow. */
function ExternalIcon() {
  return (
    <svg
      width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className="shrink-0"
    >
      <path d="M14 3h7v7" />
      <path d="M21 3l-9 9" />
      <path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5" />
    </svg>
  );
}
