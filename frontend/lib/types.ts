// Mirrors of the backend Pydantic schemas. Keep in sync with:
//   app/calculate/schemas.py, app/ppmv/schemas.py, app/catalogue/schemas.py

export type FuelType = "diesel" | "petrol" | "electric";
export type CO2Standard = "NEDC" | "WLTP";
export type CO2Source = "scraped" | "catalogue" | "manual_required";
export type Confidence = "high" | "low";
export type MatchStatus = "auto_matched" | "candidates" | "no_match" | "not_attempted";

export interface ParsedFields {
  brand: string | null;
  model: string | null;
  variant: string | null;
  fuel_type: string | null;
  first_registration: string | null;
  power_kw: number | null;
  co2_g_km: number | null;
  price_eur: number | null;
  seat_count: number | null;
  is_new: boolean;
}

export interface CatalogueCandidate {
  catalogue_id: number | null;
  brand: string;
  model: string;
  variant: string;
  price_eur: number;
  co2_g_km: number | null;
  co2_standard: string | null;
  fuel_type: string | null;
  power_kw: number | null;
  valid_from: string | null;
  score: number;
}

export interface CatalogueSearchResponse {
  status: MatchStatus;
  matched: CatalogueCandidate | null;
  candidates: CatalogueCandidate[];
}

export interface CalculateResponse {
  ppmv_eur: number | null;
  parsed: ParsedFields;
  co2_source: CO2Source;
  confidence: Confidence;
  warnings: string[];
  debug: Record<string, unknown> | null;
  match_status: MatchStatus;
  candidates: CatalogueCandidate[];
}

export interface PPMVRequest {
  price_eur: number;
  co2_g_km: number;
  fuel_type: FuelType;
  first_registration_date: string; // YYYY-MM-DD
  declaration_date: string; // YYYY-MM-DD
  eaer_city_range_km?: number;
  seat_count?: number;
  is_new_vehicle?: boolean;
}

export interface PPMVBreakdown {
  as_new_value_component: number;
  as_new_eco_component: number;
  as_new_total: number;
  vehicle_reduction_factor: number;
  depreciation_percent: number;
  months_old: number;
  final_ppmv: number;
}

export interface PPMVResponse {
  breakdown: PPMVBreakdown;
  co2_standard_used: CO2Standard;
}

export interface ApiErrorDetail {
  loc?: (string | number)[];
  msg: string;
  type?: string;
}

export class ApiError extends Error {
  status: number;
  detail: string | ApiErrorDetail[];

  constructor(status: number, detail: string | ApiErrorDetail[]) {
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join("; ")
      : detail;
    super(message);
    this.status = status;
    this.detail = detail;
  }
}
