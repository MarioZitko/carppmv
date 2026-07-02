import { ApiError, CalculateResponse, CatalogueSearchResponse, PPMVRequest, PPMVResponse } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function post<TResponse>(path: string, body: unknown): Promise<TResponse> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail = payload?.detail ?? res.statusText;
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<TResponse>;
}

async function get<TResponse>(path: string): Promise<TResponse> {
  const res = await fetch(`${BASE_URL}${path}`);

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail = payload?.detail ?? res.statusText;
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<TResponse>;
}

/** POST /calculate — url in, PPMV out (scrape + catalogue fallback + tax calc). */
export function calculateFromUrl(url: string): Promise<CalculateResponse> {
  return post<CalculateResponse>("/calculate", { url });
}

/** POST /ppmv/calculate — specs in, tax breakdown out. Manual-entry path. */
export function calculateFromSpecs(body: PPMVRequest): Promise<PPMVResponse> {
  return post<PPMVResponse>("/ppmv/calculate", body);
}

/** GET /catalogue/brands — distinct brand list, for the "search the database" flow. */
export function getCatalogueBrands(): Promise<string[]> {
  return get<string[]>("/catalogue/brands");
}

/** GET /catalogue/models — distinct model list for one brand, used as search suggestions. */
export function getCatalogueModels(brand: string): Promise<string[]> {
  return get<string[]>(`/catalogue/models?brand=${encodeURIComponent(brand)}`);
}

/** GET /catalogue/search — fuzzy brand+model+variant search against the catalogue.
 * `year` (first-registration year) reorders results to prefer the catalogue
 * price/CO2 period closest to that year, since the same variant is often
 * re-priced across several periods. */
export function searchCatalogue(params: {
  brand: string;
  model?: string;
  variant?: string;
  year?: number;
}): Promise<CatalogueSearchResponse> {
  const qs = new URLSearchParams();
  qs.set("brand", params.brand);
  if (params.model) qs.set("model", params.model);
  if (params.variant) qs.set("variant", params.variant);
  if (params.year) qs.set("year", String(params.year));
  return get<CatalogueSearchResponse>(`/catalogue/search?${qs.toString()}`);
}
