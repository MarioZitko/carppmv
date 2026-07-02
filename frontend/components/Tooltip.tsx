"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  text: string;
}

/** Small "?" info icon that reveals an explanation on click (and hover on
 * desktop) — used to explain non-obvious fields like seat count / declaration
 * date without cluttering the form with permanent help text. */
export function Tooltip({ text }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  return (
    <span className="relative inline-flex" ref={ref}>
      <button
        type="button"
        aria-label="Objašnjenje"
        onClick={() => setOpen((v) => !v)}
        onMouseEnter={() => setOpen(true)}
        className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-[var(--border)] text-[10px] font-semibold text-[var(--text-soft)] hover:bg-[var(--primary)] hover:text-white transition-colors"
      >
        ?
      </button>
      {open && (
        <span className="absolute z-20 bottom-full left-1/2 -translate-x-1/2 mb-2 w-60 rounded-lg bg-[var(--text)] text-white text-xs leading-relaxed px-3 py-2 shadow-lg">
          {text}
          <span className="absolute top-full left-1/2 -translate-x-1/2 h-2 w-2 rotate-45 bg-[var(--text)]" />
        </span>
      )}
    </span>
  );
}
