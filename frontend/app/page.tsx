"use client";

import { useEffect, useState } from "react";
import { UrlInputForm } from "@/components/UrlInputForm";
import { CatalogueSearchForm } from "@/components/CatalogueSearchForm";
import { CandidatesList } from "@/components/CandidatesList";
import { VehicleForm } from "@/components/VehicleForm";
import { PriceFineTune } from "@/components/PriceFineTune";
import { PPMVBreakdownCard } from "@/components/PPMVBreakdownCard";
import { CarVerticalCard } from "@/components/CarVerticalCard";
import { ParsedFieldsCard } from "@/components/ParsedFieldsCard";
import { calculateFromUrl, calculateFromSpecs } from "@/lib/api";
import { normalizeUrl } from "@/lib/format";
import { guessFuelType, toIsoDate, todayIso } from "@/lib/fuel";
import { buildPpmvRequest, emptyVehicleForm, VehicleFormValues } from "@/lib/vehicleForm";
import { ApiError, CalculateResponse, CatalogueCandidate, CatalogueSearchResponse, PPMVResponse } from "@/lib/types";

type EntryMode = "link" | "search";

export default function Home() {
  const [mode, setMode] = useState<EntryMode>("link");

  const [urlLoading, setUrlLoading] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [urlResult, setUrlResult] = useState<CalculateResponse | null>(null);

  const [searchResult, setSearchResult] = useState<CatalogueSearchResponse | null>(null);

  const [selectedCatalogueId, setSelectedCatalogueId] = useState<number | null>(null);
  const [form, setForm] = useState<VehicleFormValues>(() => emptyVehicleForm(todayIso()));
  // Bumped whenever priceEur is set from a new authoritative source (a parsed
  // listing URL or a picked catalogue candidate) so PriceFineTune's extras
  // anchor force-resets instead of only recentering when out of its old range.
  const [priceAnchorToken, setPriceAnchorToken] = useState(0);

  const [ppmvResult, setPpmvResult] = useState<PPMVResponse | null>(null);
  const [ppmvLoading, setPpmvLoading] = useState(false);
  const [ppmvApiError, setPpmvApiError] = useState<string | null>(null);

  const validationOutcome = buildPpmvRequest(form);
  const validationError = typeof validationOutcome === "string" ? validationOutcome : null;
  const ppmvHint = validationError ?? ppmvApiError;

  function patchForm(patch: Partial<VehicleFormValues>) {
    setForm((prev) => ({ ...prev, ...patch }));
  }

  function applyCandidate(candidate: CatalogueCandidate) {
    setSelectedCatalogueId(candidate.catalogue_id);
    patchForm({
      priceEur: String(candidate.price_eur),
      co2: candidate.co2_g_km !== null ? String(candidate.co2_g_km) : form.co2,
      fuelType: candidate.fuel_type === "diesel" || candidate.fuel_type === "petrol" ? candidate.fuel_type : form.fuelType,
    });
    setPriceAnchorToken((t) => t + 1);
  }

  async function handleUrlSubmit(rawUrl: string) {
    setUrlLoading(true);
    setUrlError(null);
    setUrlResult(null);
    setSearchResult(null);
    setSelectedCatalogueId(null);
    try {
      const data = await calculateFromUrl(normalizeUrl(rawUrl));
      setUrlResult(data);

      patchForm({
        priceEur: data.parsed.price_eur !== null ? String(data.parsed.price_eur) : "",
        co2: data.parsed.co2_g_km !== null ? String(data.parsed.co2_g_km) : "",
        fuelType: guessFuelType(data.parsed.fuel_type),
        regDate: toIsoDate(data.parsed.first_registration),
        seatCount: data.parsed.seat_count !== null ? String(data.parsed.seat_count) : "",
        isNew: data.parsed.is_new,
      });
      setPriceAnchorToken((t) => t + 1);

      if (data.match_status === "auto_matched" && data.candidates.length > 0) {
        setSelectedCatalogueId(data.candidates[0].catalogue_id);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setUrlError("mobile.de trenutno nije podržan u ovom načinu — koristite pretragu baze vozila ili unesite podatke ručno.");
      } else if (err instanceof ApiError) {
        setUrlError(err.message);
      } else {
        setUrlError("Ne mogu se povezati s API-jem kalkulatora. Je li backend pokrenut?");
      }
    } finally {
      setUrlLoading(false);
    }
  }

  function handleSearchResult(result: CatalogueSearchResponse | null) {
    setSearchResult(result);
    setUrlResult(null);
    setSelectedCatalogueId(null);
  }

  // Live recalculation — every change to the vehicle form debounces into a
  // fresh PPMV calculation, so the price fine-tune sidebar and candidate
  // picker both feel instant without needing an explicit "submit".
  useEffect(() => {
    if (typeof validationOutcome === "string") return;

    const timer = setTimeout(async () => {
      setPpmvLoading(true);
      try {
        const data = await calculateFromSpecs(validationOutcome);
        setPpmvResult(data);
        setPpmvApiError(null);
      } catch (err) {
        setPpmvApiError(err instanceof ApiError ? err.message : "Izračun trenutno nije dostupan.");
      } finally {
        setPpmvLoading(false);
      }
    }, 350);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.priceEur, form.co2, form.fuelType, form.regDate, form.declDate, form.seatCount, form.isNew]);

  const candidates = urlResult?.candidates ?? searchResult?.candidates ?? [];
  const showCandidates = candidates.length > 0;

  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 sm:py-8">
      <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[var(--text)] mb-1">
        Izračun PPMV-a
      </h1>
      <p className="text-sm text-[var(--text-soft)] mb-5 max-w-2xl">
        Procijenite hrvatski posebni porez na motorna vozila (PPMV) — zalijepite link oglasa ili odaberite
        vozilo izravno iz baze podataka, a cijenu i CO2 uvijek možete naknadno fino podesiti.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        <div className="lg:col-span-2 space-y-4">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm p-4">
            <div className="flex gap-1 mb-3 rounded-xl bg-[var(--surface-alt)] p-1 w-fit overflow-x-auto">
              <button
                type="button"
                onClick={() => setMode("link")}
                className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
                  mode === "link" ? "bg-[var(--surface)] text-[var(--primary)] shadow-sm" : "text-[var(--text-soft)]"
                }`}
              >
                Iz linka oglasa
              </button>
              <button
                type="button"
                onClick={() => setMode("search")}
                className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
                  mode === "search"
                    ? "bg-[var(--surface)] text-[var(--primary)] shadow-sm"
                    : "text-[var(--text-soft)]"
                }`}
              >
                Pretraži bazu vozila
              </button>
            </div>

            {mode === "link" ? (
              <UrlInputForm onSubmit={handleUrlSubmit} loading={urlLoading} />
            ) : (
              <CatalogueSearchForm onResult={handleSearchResult} />
            )}

            {urlError && (
              <p className="mt-3 text-sm text-[var(--err)] rounded-xl border border-[var(--err)]/30 bg-[var(--err-bg)] px-4 py-2.5">
                {urlError}
              </p>
            )}
          </div>

          {urlResult && <ParsedFieldsCard parsed={urlResult.parsed} warnings={urlResult.warnings} />}

          {showCandidates && (
            <CandidatesList
              candidates={candidates}
              selectedCatalogueId={selectedCatalogueId}
              onSelect={applyCandidate}
            />
          )}

          <VehicleForm values={form} onChange={patchForm} />
        </div>

        <div className="lg:sticky lg:top-24 space-y-4">
          <PriceFineTune
            priceEur={Number(form.priceEur) || 0}
            onChange={(price) => patchForm({ priceEur: String(price) })}
            anchorToken={priceAnchorToken}
          />

          {ppmvResult ? (
            <>
              <PPMVBreakdownCard result={ppmvResult} updating={ppmvLoading} />
              <CarVerticalCard />
            </>
          ) : (
            <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-alt)] px-5 py-6 text-sm text-[var(--text-soft)]">
              {ppmvHint ?? "Popunite podatke o vozilu za izračun PPMV-a."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
