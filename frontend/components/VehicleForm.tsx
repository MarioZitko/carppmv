"use client";

import { Tooltip } from "@/components/Tooltip";
import { ToggleSwitch } from "@/components/ToggleSwitch";
import { VehicleFormValues } from "@/lib/vehicleForm";
import { FuelType } from "@/lib/types";

interface Props {
  values: VehicleFormValues;
  onChange: (patch: Partial<VehicleFormValues>) => void;
}

/** Controlled vehicle-detail form — the single source of truth for the specs
 * that feed the PPMV calculation. Lives fully in parent state (not local
 * state) so the price fine-tune sidebar and the catalogue candidate picker
 * can both drive it and trigger a live recalculation. First registration date
 * comes prefilled straight from the parsed listing (see page.tsx) — still a
 * plain editable date field in case the parse got it wrong. */
export function VehicleForm({ values, onChange }: Props) {
  const label = "block text-xs font-medium uppercase tracking-wide text-[var(--text-soft)] mb-1";
  const input =
    "w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)] transition-colors disabled:opacity-50 disabled:bg-[var(--surface-alt)]";

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm p-4 space-y-4">
      <h3 className="text-sm font-semibold text-[var(--text)]">Podaci o vozilu</h3>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        <div>
          <label className={label}>Cijena (EUR)</label>
          <input
            className={input}
            type="number"
            min="0"
            step="1"
            value={values.priceEur}
            onChange={(e) => onChange({ priceEur: e.target.value })}
          />
        </div>

        <div>
          <label className={label}>Vrsta goriva</label>
          <select
            className={input}
            value={values.fuelType}
            onChange={(e) => onChange({ fuelType: e.target.value as FuelType | "" })}
          >
            <option value="">Odaberite…</option>
            <option value="diesel">Dizel</option>
            <option value="petrol">Benzin</option>
            <option value="electric">Električno</option>
          </select>
        </div>

        <div>
          <label className={label}>CO2 (g/km)</label>
          <input
            className={input}
            type="number"
            min="0"
            step="1"
            value={values.fuelType === "electric" ? "0" : values.co2}
            onChange={(e) => onChange({ co2: e.target.value })}
            disabled={values.fuelType === "electric"}
          />
        </div>

        <div>
          <label className={`${label} flex items-center`}>
            Broj sjedala (opc.)
            <Tooltip text="Vozila s 8 ukupnih sjedala (7+1) imaju sniženu poreznu osnovicu za 50%, a s 9+ sjedala (8+1) za 75% — kombiji i veća vozila registrirana kao osobna time plaćaju znatno manji PPMV." />
          </label>
          <input
            className={input}
            type="number"
            min="1"
            value={values.seatCount}
            onChange={(e) => onChange({ seatCount: e.target.value })}
          />
        </div>

        <div>
          <label className={label}>Datum prve registracije</label>
          <input
            className={input}
            type="date"
            value={values.regDate}
            onChange={(e) => onChange({ regDate: e.target.value })}
          />
        </div>

        <div>
          <label className={`${label} flex items-center`}>
            Datum deklaracije
            <Tooltip text="Datum kada se vozilo prijavljuje carini u Hrvatskoj. Razlika između ovog datuma i datuma prve registracije određuje starost vozila u mjesecima, koja izravno smanjuje poreznu osnovicu kroz tablicu amortizacije (npr. vozilo staro 5 godina plaća samo ~40% PPMV-a novog vozila)." />
          </label>
          <input
            className={input}
            type="date"
            value={values.declDate}
            onChange={(e) => onChange({ declDate: e.target.value })}
          />
        </div>
      </div>

      <div className="pt-3 border-t border-[var(--border)]">
        <ToggleSwitch
          checked={values.isNew}
          onChange={(v) => onChange({ isNew: v })}
          label="Novo vozilo"
          hint="Uključite ako vozilo nije prethodno registrirano — amortizacija se tada ne primjenjuje."
        />
      </div>
    </div>
  );
}
