"use client";

import { useState } from "react";
import { Tooltip } from "@/components/Tooltip";
import { ToggleSwitch } from "@/components/ToggleSwitch";
import { DateInput } from "@/components/DateInput";
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
	// Gates the red error border: a pristine, untouched field shouldn't look
	// like the user did something wrong before they've even reached it.
	const [touched, setTouched] = useState<Record<string, boolean>>({});
	function markTouched(field: string) {
		setTouched((prev) => (prev[field] ? prev : { ...prev, [field]: true }));
	}

	const label =
		"block text-xs font-medium uppercase tracking-wide text-[var(--text-soft)] mb-1";
	const input =
		"w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 py-2 text-sm text-[var(--text)] focus:border-[var(--primary)] transition-colors disabled:opacity-50 disabled:bg-[var(--surface-alt)]";
	const errInput = `${input} border-[var(--err)] focus:border-[var(--err)]`;

	const hasMoreSeats = values.seatCount !== "" && Number(values.seatCount) >= 8;
	const is9Plus = Number(values.seatCount) >= 9;

	const priceMissing = !values.priceEur || Number(values.priceEur) <= 0;
	const co2Missing =
		values.fuelType !== "electric" && (!values.co2 || Number(values.co2) <= 0);
	const fuelMissing = !values.fuelType;
	const regDateMissing = !values.regDate;
	const declDateMissing = !values.declDate;

	return (
		<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm p-4 space-y-4">
			<h3 className="text-sm font-semibold text-[var(--text)]">
				Podaci o vozilu
			</h3>
			<p className="text-xs text-[var(--text-soft)] italic">
				Napomena: baza sadrži cijene osnovnih izvedbi (trim varijanti) bez
				dodatne opreme. Stvarna cijena novog vozila može biti viša zbog paketa
				opreme i dodatne opreme, a to može utjecati i na CO2 emisiju, a time i
				na iznos PPMV-a.
			</p>

			<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
				<div>
					<label className={label} htmlFor="vf-price">Cijena (EUR)</label>
					<input
						id="vf-price"
						className={priceMissing && touched.priceEur ? errInput : input}
						type="number"
						min="0"
						step="1"
						value={values.priceEur}
						onChange={(e) => onChange({ priceEur: e.target.value })}
						onBlur={() => markTouched("priceEur")}
					/>
				</div>

				<div>
					<label className={label} htmlFor="vf-fuel">Vrsta goriva</label>
					<select
						id="vf-fuel"
						className={fuelMissing && touched.fuelType ? errInput : input}
						value={values.fuelType}
						onChange={(e) =>
							onChange({ fuelType: e.target.value as FuelType | "" })
						}
						onBlur={() => markTouched("fuelType")}
					>
						<option value="">Odaberite…</option>
						<option value="diesel">Dizel</option>
						<option value="petrol">Benzin</option>
						<option value="electric">Električno</option>
					</select>
				</div>

				<div>
					<label className={label} htmlFor="vf-co2">CO2 (g/km)</label>
					<input
						id="vf-co2"
						className={co2Missing && touched.co2 ? errInput : input}
						type="number"
						min="0"
						step="1"
						value={values.fuelType === "electric" ? "0" : values.co2}
						onChange={(e) => onChange({ co2: e.target.value })}
						onBlur={() => markTouched("co2")}
						disabled={values.fuelType === "electric"}
					/>
				</div>

				<div>
					<label className={label} htmlFor="vf-reg-date">Datum prve registracije</label>
					<DateInput
						id="vf-reg-date"
						className={regDateMissing && touched.regDate ? errInput : input}
						value={values.regDate}
						onChange={(v) => onChange({ regDate: v })}
						onBlur={() => markTouched("regDate")}
					/>
				</div>

				<div>
					<label className={`${label} flex items-center`} htmlFor="vf-decl-date">
						Datum deklaracije
						<Tooltip text="Datum kada se vozilo prijavljuje carini u Hrvatskoj. Razlika između ovog datuma i datuma prve registracije određuje starost vozila u mjesecima, koja izravno smanjuje poreznu osnovicu kroz tablicu amortizacije (npr. vozilo staro 5 godina plaća samo ~40% PPMV-a novog vozila)." />
					</label>
					<DateInput
						id="vf-decl-date"
						className={declDateMissing && touched.declDate ? errInput : input}
						value={values.declDate}
						onChange={(v) => onChange({ declDate: v })}
						onBlur={() => markTouched("declDate")}
					/>
				</div>
			</div>

			<div className="pt-3 border-t border-[var(--border)] space-y-3">
				<ToggleSwitch
					checked={values.isNew}
					onChange={(v) => onChange({ isNew: v })}
					label="Novo vozilo"
					hint="Uključite ako vozilo nije prethodno registrirano — amortizacija se tada ne primjenjuje."
				/>

				<div>
					<ToggleSwitch
						checked={hasMoreSeats}
						onChange={(v) => onChange({ seatCount: v ? "8" : "" })}
						label="Vozilo ima više sjedala"
						hint="Kombiji/kamperi (7+1 ili 8+1) registrirani kao osobna vozila imaju sniženu poreznu osnovicu."
					/>
					{hasMoreSeats && (
						<div className="mt-2 flex gap-1 rounded-xl bg-[var(--surface-alt)] p-1 w-fit">
							<button
								type="button"
								onClick={() => onChange({ seatCount: "8" })}
								className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
									!is9Plus
										? "bg-[var(--surface)] text-[var(--primary)] shadow-sm"
										: "text-[var(--text-soft)]"
								}`}
							>
								8 sjedala (7+1) — 50%
							</button>
							<button
								type="button"
								onClick={() => onChange({ seatCount: "9" })}
								className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
									is9Plus
										? "bg-[var(--surface)] text-[var(--primary)] shadow-sm"
										: "text-[var(--text-soft)]"
								}`}
							>
								9+ sjedala (8+1) — 75%
							</button>
						</div>
					)}
				</div>
			</div>
		</div>
	);
}
