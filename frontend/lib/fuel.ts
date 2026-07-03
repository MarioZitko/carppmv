import { FuelType } from "./types";

const FUEL_MAP: Record<string, FuelType> = {
  diesel: "diesel",
  dizel: "diesel",
  petrol: "petrol",
  benzin: "petrol",
  gasoline: "petrol",
  electric: "electric",
  elektrisch: "electric",
  elektro: "electric",
};

export function guessFuelType(raw: string | null): FuelType | "" {
  if (!raw) return "";
  return FUEL_MAP[raw.trim().toLowerCase()] ?? "";
}

/** Parses whatever date format a scraper handed back into "YYYY-MM-DD", or ""
 * if unparseable. Listing sites are inconsistent about this — ISO datetimes
 * with a time suffix, single-digit day/month, a trailing "." (Croatian
 * convention), slash-separated dates, "MM/YYYY", or a bare year are all seen
 * in practice, so this is deliberately lenient rather than requiring one
 * exact shape. */
export function toIsoDate(raw: string | null): string {
  if (!raw) return "";

  // ISO date, optionally with a time component ("2021-05-17T00:00:00.000Z").
  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;

  // Normalize whitespace around separators ("17. 05. 2021." -> "17.05.2021").
  const text = raw.trim().replace(/\s*([./])\s*/g, "$1");

  let m = text.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})\.?$/);
  if (m) return `${m[3]}-${pad2(m[2])}-${pad2(m[1])}`;

  m = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (m) return `${m[3]}-${pad2(m[2])}-${pad2(m[1])}`;

  m = text.match(/^(\d{1,2})\/(\d{4})$/);
  if (m) return `${m[2]}-${pad2(m[1])}-01`;

  // Day-less month.year, dot-separated ("05.2021.") — seen on autobid.de.
  m = text.match(/^(\d{1,2})\.(\d{4})\.?$/);
  if (m) return `${m[2]}-${pad2(m[1])}-01`;

  m = text.match(/^(\d{4})-(\d{1,2})$/);
  if (m) return `${m[1]}-${pad2(m[2])}-01`;

  m = text.match(/^(\d{4})$/);
  if (m) return `${m[1]}-01-01`;

  return "";
}

function pad2(n: string): string {
  return n.padStart(2, "0");
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
