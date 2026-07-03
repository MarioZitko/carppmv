"use client";

import { useEffect, useState } from "react";

interface Props {
  value: string; // ISO yyyy-mm-dd, or ""
  onChange: (isoValue: string) => void;
  className?: string;
}

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

/** Text input that displays/accepts dates as dd/mm/yyyy (auto-inserting the
 * slashes as the user types) while emitting/accepting plain ISO yyyy-mm-dd
 * strings, since that's what the rest of the form and the API expect. Kept
 * as a local text buffer rather than a controlled reformat-on-every-keystroke
 * value so the cursor doesn't jump mid-edit. */
export function DateInput({ value, onChange, className }: Props) {
  const [text, setText] = useState(() => isoToDisplay(value));

  useEffect(() => {
    setText(isoToDisplay(value));
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
    onChange(displayToIso(formatted));
  }

  return (
    <input
      type="text"
      inputMode="numeric"
      placeholder="dd/mm/gggg"
      maxLength={10}
      className={className}
      value={text}
      onChange={(e) => handleChange(e.target.value)}
    />
  );
}
