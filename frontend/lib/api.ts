import { ApiError, CalculateResponse, CatalogueSearchResponse, PPMVRequest, PPMVResponse, WikipediaEngineSearchResponse, WikipediaModelListResponse } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Scraping (Playwright/Apify) is the slowest path the backend serves — give
// requests real headroom before treating the backend as hung, rather than
// leaving a caller's loading state spinning forever with no way out.
const REQUEST_TIMEOUT_MS = 30_000;

/** Thrown when a request is aborted for exceeding REQUEST_TIMEOUT_MS, so
 * callers can show a distinct "the server is taking too long" message
 * instead of the generic network-failure one ApiError's absence implies. */
export class ApiTimeoutError extends Error {
  constructor() {
    super("Request timed out");
  }
}

interface RequestOptions {
  method: "GET" | "POST";
  body?: unknown;
}

async function request<TResponse>(path: string, options: RequestOptions): Promise<TResponse> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method: options.method,
      headers: options.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiTimeoutError();
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail = payload?.detail ?? res.statusText;
    throw new ApiError(res.status, detail);
  }

  return res.json() as Promise<TResponse>;
}

/** POST /calculate — url in, PPMV out (scrape + catalogue fallback + tax calc).
 * turnstileToken is only enforced by the backend for the mobile.de path, and
 * only when TURNSTILE_SECRET_KEY is configured there. */
export function calculateFromUrl(url: string, turnstileToken?: string | null): Promise<CalculateResponse> {
  return request<CalculateResponse>("/calculate", {
    method: "POST",
    body: { url, turnstile_token: turnstileToken ?? null },
  });
}

/** POST /ppmv/calculate — specs in, tax breakdown out. Manual-entry path. */
export function calculateFromSpecs(body: PPMVRequest): Promise<PPMVResponse> {
  return request<PPMVResponse>("/ppmv/calculate", { method: "POST", body });
}

/** GET /catalogue/brands — distinct brand list, for the "search the database" flow. */
export function getCatalogueBrands(): Promise<string[]> {
  return request<string[]>("/catalogue/brands", { method: "GET" });
}

/** GET /catalogue/models — distinct model list for one brand, used as search suggestions. */
export function getCatalogueModels(brand: string): Promise<string[]> {
  return request<string[]>(`/catalogue/models?brand=${encodeURIComponent(brand)}`, { method: "GET" });
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
  powerKw?: number;
}): Promise<CatalogueSearchResponse> {
  const qs = new URLSearchParams();
  qs.set("brand", params.brand);
  if (params.model) qs.set("model", params.model);
  if (params.variant) qs.set("variant", params.variant);
  if (params.year) qs.set("year", String(params.year));
  if (params.powerKw) qs.set("power_kw", String(params.powerKw));
  return request<CatalogueSearchResponse>(`/catalogue/search?${qs.toString()}`, { method: "GET" });
}

/** GET /wikipedia/brands — the marques the Wikipedia corpus actually holds
 * (37, against the catalogue's 43). It is the picker's zeroth step, reached
 * whenever no listing has told us the brand — which is the whole point of the
 * picker being openable on an empty form. Deliberately the corpus's own list
 * and not `getCatalogueBrands()`: offering a marque the corpus has nothing for
 * only leads to an empty model list that looks broken. */
export function getWikipediaBrands(): Promise<string[]> {
  return request<string[]>("/wikipedia/brands", { method: "GET" });
}

/** GET /wikipedia/models — the picker's model step: which generation is it? */
export function searchWikipediaModels(params: {
  brand: string;
  q?: string;
  registered?: string | null;
}): Promise<WikipediaModelListResponse> {
  const qs = new URLSearchParams();
  qs.set("brand", params.brand);
  if (params.q) qs.set("q", params.q);
  if (params.registered) qs.set("registered", params.registered);
  return request<WikipediaModelListResponse>(`/wikipedia/models?${qs.toString()}`, {
    method: "GET",
  });
}

/** GET /wikipedia/engines — every Wikipedia engine row for a brand, optionally
 * narrowed by free-text model/engine designation. Backs the engine picker,
 * which is how a user resolves ties the matcher can't (an Audi A2 "1.4" at
 * 55 kW is both a 142 g/km petrol and a 116 g/km diesel). */
export function searchWikipediaEngines(params: {
  brand: string;
  q?: string;
  /** Exact model_article_title from the model step. */
  article?: string | null;
  /** ISO date. Scopes the list to generations that could plausibly have been
   * registered then — the difference between offering a 2019 G20 and the
   * 2016 F30 the listing is actually about. */
  registered?: string | null;
}): Promise<WikipediaEngineSearchResponse> {
  const qs = new URLSearchParams();
  qs.set("brand", params.brand);
  if (params.q) qs.set("q", params.q);
  if (params.article) qs.set("article", params.article);
  if (params.registered) qs.set("registered", params.registered);
  return request<WikipediaEngineSearchResponse>(`/wikipedia/engines?${qs.toString()}`, {
    method: "GET",
  });
}
