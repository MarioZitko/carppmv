"use client";

import { FormEvent, useEffect, useState } from "react";
import { getCatalogueBrands, getCatalogueModels, searchCatalogue } from "@/lib/api";
import { ApiError, CatalogueSearchResponse } from "@/lib/types";

interface Props {
  onResult: (result: CatalogueSearchResponse | null) => void;
}

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 41 }, (_, i) => CURRENT_YEAR - i);

/** Search the ingested vehicle database directly by brand/model/variant —
 * no listing link required. Powers the "pick a vehicle from the database"
 * flow, using the same fuzzy matcher the URL-scrape path uses internally.
 * Model suggestions (datalist) come from the brand's known catalogue models,
 * but the actual match is still fuzzy — picking a suggestion isn't required. */
export function CatalogueSearchForm({ onResult }: Props) {
  const [brands, setBrands] = useState<string[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [variant, setVariant] = useState("");
  const [year, setYear] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCatalogueBrands()
      .then(setBrands)
      .catch(() => setBrands([]));
  }, []);

  useEffect(() => {
    if (!brand) return;
    getCatalogueModels(brand)
      .then(setModels)
      .catch(() => setModels([]));
  }, [brand]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!brand) {
      setError("Odaberite marku vozila.");
      return;
    }
    setError(null);
    setLoading(true);
    onResult(null);
    try {
      const result = await searchCatalogue({ brand, model, variant, year: year ? Number(year) : undefined });
      onResult(result);
      if (result.candidates.length === 0 && !result.matched) {
        setError("Nema podudaranja u bazi vozila za uneseni model/varijantu.");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Baza vozila trenutno nije dostupna.");
    } finally {
      setLoading(false);
    }
  }

  const inputCls =
    "w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2 text-sm text-[var(--text)] placeholder:text-[var(--text-soft)] focus:border-[var(--primary)] transition-colors";

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <select
          className={inputCls}
          value={brand}
          onChange={(e) => {
            setBrand(e.target.value);
            setModels([]);
          }}
        >
          <option value="">Marka…</option>
          {brands.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>

        <div>
          <input
            className={inputCls}
            placeholder="Model (npr. 320d, A4…)"
            list="catalogue-model-suggestions"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
          <datalist id="catalogue-model-suggestions">
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </div>

        <input
          className={inputCls}
          placeholder="Varijanta / oprema (opc.)"
          value={variant}
          onChange={(e) => setVariant(e.target.value)}
        />

        <select className={inputCls} value={year} onChange={(e) => setYear(e.target.value)}>
          <option value="">Godina (opc.)</option>
          {YEARS.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="rounded-xl bg-[var(--primary)] px-5 py-2 text-sm font-semibold text-white shadow-sm hover:bg-[var(--primary-dark)] disabled:opacity-40 transition-colors"
      >
        {loading ? "Pretraživanje…" : "Pretraži bazu vozila"}
      </button>

      {error && <p className="text-sm text-[var(--err)]">{error}</p>}
    </form>
  );
}
