"use client";

import { useEffect, useState } from "react";

interface Props {
  value: string; // ISO yyyy-mm-dd, or ""
  onChange: (isoValue: string) => void;
  className?: string;
}

const MIN_YEAR = 1980;
const MAX_YEAR = new Date().getFullYear() + 1;

function isoToDisplay(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return "";
  return `${m[3]}/${m[2]}/${m[1]}`;
}

function displayToIso(display: string): string {
  const m = display.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!m) return "";
  const [, dd, mm, yyyy] = m;
  return `${yyyy}-${mm}-${dd}`;
}

/** Validates a complete "dd/mm/yyyy" display string, returning null when
 * valid or a short Croatian error message otherwise. Round-trips a real Date
 * to catch calendar-impossible combinations (31/02, 30/13, non-leap Feb 29)
 * that the regex shape alone can't detect. */
function validateDisplayDate(display: string): string | null {
  const m = display.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!m) return null;
  const day = Number(m[1]);
  const month = Number(m[2]);
  const year = Number(m[3]);

  if (year < MIN_YEAR || year > MAX_YEAR) {
    return `Godina mora biti između ${MIN_YEAR} i ${MAX_YEAR}.`;
  }
  if (month < 1 || month > 12) {
    return "Neispravan datum.";
  }

  const date = new Date(year, month - 1, day);
  const roundTripOk =
    date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
  if (!roundTripOk) {
    return "Neispravan datum.";
  }

  return null;
}

/** Text input that displays/accepts dates as dd/mm/yyyy (auto-inserting the
 * slashes as the user types) while emitting/accepting plain ISO yyyy-mm-dd
 * strings, since that's what the rest of the form and the API expect. Kept
 * as a local text buffer rather than a controlled reformat-on-every-keystroke
 * value so the cursor doesn't jump mid-edit. Once a full date is typed it's
 * checked for real calendar/year validity, not just the dd/mm/yyyy shape. */
export function DateInput({ value, onChange, className }: Props) {
  const [text, setText] = useState(() => isoToDisplay(value));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setText(isoToDisplay(value));
    setError(null);
  }, [value]);

  function handleChange(raw: string) {
    const digits = raw.replace(/\D/g, "").slice(0, 8);
    let formatted = digits;
    if (digits.length > 4) {
      formatted = `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
    } else if (digits.length > 2) {
      formatted = `${digits.slice(0, 2)}/${digits.slice(2)}`;
    }
    setText(formatted);

    if (digits.length < 8) {
      setError(null);
      onChange(displayToIso(formatted));
      return;
    }

    const validationMsg = validateDisplayDate(formatted);
    setError(validationMsg);
    onChange(validationMsg ? "" : displayToIso(formatted));
  }

  return (
    <div>
      <input
        type="text"
        inputMode="numeric"
        placeholder="dd/mm/gggg"
        maxLength={10}
        className={`${className ?? ""} ${error ? "border-[var(--err)] focus:border-[var(--err)]" : ""}`}
        value={text}
        onChange={(e) => handleChange(e.target.value)}
      />
      {error && <p className="mt-1 text-xs text-[var(--err)]">{error}</p>}
    </div>
  );
}
