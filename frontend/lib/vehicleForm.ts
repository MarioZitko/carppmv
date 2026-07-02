import { FuelType, PPMVRequest } from "./types";

export interface VehicleFormValues {
  priceEur: string;
  co2: string;
  fuelType: FuelType | "";
  regDate: string;
  declDate: string;
  seatCount: string;
  isNew: boolean;
}

export function emptyVehicleForm(declDate: string): VehicleFormValues {
  return {
    priceEur: "",
    co2: "",
    fuelType: "",
    regDate: "",
    declDate,
    seatCount: "",
    isNew: false,
  };
}

/** Returns the PPMVRequest if the form is complete/valid, otherwise a
 * human-readable Croatian error string. Shared by the live-recalculation
 * effect and the manual submit handler so validation only lives in one place. */
export function buildPpmvRequest(v: VehicleFormValues): PPMVRequest | string {
  if (!v.fuelType) return "Odaberite vrstu goriva.";
  const price = Number(v.priceEur);
  if (!price || price <= 0) return "Unesite ispravnu cijenu.";
  const co2Value = v.fuelType === "electric" ? 0 : Number(v.co2);
  if (v.fuelType !== "electric" && (!co2Value || co2Value <= 0))
    return "Unesite ispravnu CO2 vrijednost (g/km).";
  if (!v.regDate) return "Unesite datum prve registracije.";
  if (!v.declDate) return "Unesite datum deklaracije.";
  if (v.declDate < v.regDate) return "Datum deklaracije ne može biti prije datuma prve registracije.";

  const request: PPMVRequest = {
    price_eur: price,
    co2_g_km: co2Value,
    fuel_type: v.fuelType,
    first_registration_date: v.regDate,
    declaration_date: v.declDate,
    is_new_vehicle: v.isNew,
  };
  if (v.seatCount) request.seat_count = Number(v.seatCount);
  return request;
}
