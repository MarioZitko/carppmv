"use client";

interface Props {
  value: string; // ISO yyyy-mm-dd, or ""
  onChange: (isoValue: string) => void;
  className?: string;
  onBlur?: () => void;
}

const MIN_YEAR = 1980;
const MAX_YEAR = new Date().getFullYear() + 1;
const MIN_DATE = `${MIN_YEAR}-01-01`;
const MAX_DATE = `${MAX_YEAR}-12-31`;

/** Native calendar date picker, constrained to a sane year range. Emits/accepts
 * plain ISO yyyy-mm-dd strings, since that's what the rest of the form and the
 * API expect — the browser handles locale display, calendar affordance, and
 * calendar-impossible-date rejection for us. */
export function DateInput({ value, onChange, className, onBlur }: Props) {
  return (
    <input
      type="date"
      lang="hr"
      min={MIN_DATE}
      max={MAX_DATE}
      className={className}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
    />
  );
}
