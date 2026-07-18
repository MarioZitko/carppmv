"use client";

import { useEffect, useRef, useState } from "react";
import { UrlInputForm } from "@/components/UrlInputForm";
import { CatalogueSearchForm } from "@/components/CatalogueSearchForm";
import { CandidatesList } from "@/components/CandidatesList";
import { VehicleForm } from "@/components/VehicleForm";
import { PriceFineTune } from "@/components/PriceFineTune";
import { MobilePriceBar } from "@/components/MobilePriceBar";
import { PPMVBreakdownCard } from "@/components/PPMVBreakdownCard";
import { CarVerticalCard } from "@/components/CarVerticalCard";
import { ParsedFieldsCard } from "@/components/ParsedFieldsCard";
import { calculateFromUrl, calculateFromSpecs } from "@/lib/api";
import { normalizeUrl } from "@/lib/format";
import { guessFuelType, toIsoDate, todayIso } from "@/lib/fuel";
import {
	buildPpmvRequest,
	emptyVehicleForm,
	VehicleFormValues,
} from "@/lib/vehicleForm";
import {
	ApiError,
	CalculateResponse,
	CatalogueCandidate,
	CatalogueSearchResponse,
	PPMVResponse,
} from "@/lib/types";

type EntryMode = "link" | "search";

// Maps backend errors to plain, non-technical Croatian so a user who has
// never seen a stack trace still knows what happened and what to do next —
// the backend's own error text (ScrapingError/PPMVError messages) is written
// for logs, not for this audience, so it's deliberately never shown as-is.
function describeUrlError(err: unknown): string {
	if (!(err instanceof ApiError)) {
		return "Nismo se uspjeli povezati s poslužiteljem. Provjerite internetsku vezu i pokušajte ponovno.";
	}
	switch (err.status) {
		case 429:
			return "Previše zahtjeva s ove adrese — pričekajte nekoliko minuta pa pokušajte ponovno.";
		case 403:
			return "Sigurnosna provjera nije uspjela — osvježite stranicu i pokušajte ponovno zalijepiti link.";
		case 503:
			return "Dnevni limit automatskog dohvata oglasa je dostignut — unesite podatke o vozilu ručno u nastavku.";
		case 422:
			return "Ne prepoznajemo ovaj link — provjerite je li to poveznica na oglas s podržane stranice (autoscout24, autobid.de, mobile.de), ili unesite podatke ručno u nastavku.";
		case 404:
			return "Oglas nije pronađen — možda je uklonjen ili je poveznica netočna. Unesite podatke ručno u nastavku.";
		case 502:
		case 504:
			return "Stranica oglasa trenutno nije dostupna — oglas je možda uklonjen, istekao ili stranica privremeno ne odgovara. Unesite podatke ručno u nastavku.";
		case 400:
			return "Podaci iz oglasa (npr. cijena ili CO2) izgledaju neispravni pa izračun nije moguć — provjerite oglas ili unesite podatke ručno u nastavku.";
		default:
			return "Nešto je pošlo po zlu prilikom čitanja oglasa — pokušajte ponovno ili unesite podatke ručno u nastavku.";
	}
}

// Same idea for the manual vehicle-data form — the engine's validation
// errors (out-of-range price/CO2 brackets) are also written in English for
// logs, so translate them into something an average user can act on.
function describePpmvError(err: unknown): string {
	if (!(err instanceof ApiError)) {
		return "Izračun trenutno nije dostupan — pokušajte ponovno za trenutak.";
	}
	if (err.status === 400) {
		return "Unesena cijena ili CO2 vrijednost je izvan očekivanog raspona — provjerite jesu li podaci točni.";
	}
	return "Izračun trenutno nije dostupan — pokušajte ponovno za trenutak.";
}

export default function Home() {
	const [mode, setMode] = useState<EntryMode>("link");

	const [urlLoading, setUrlLoading] = useState(false);
	const [urlError, setUrlError] = useState<string | null>(null);
	const [urlResult, setUrlResult] = useState<CalculateResponse | null>(null);

	const [searchResult, setSearchResult] =
		useState<CatalogueSearchResponse | null>(null);

	const [selectedCatalogueId, setSelectedCatalogueId] = useState<number | null>(
		null,
	);
	const [form, setForm] = useState<VehicleFormValues>(() =>
		emptyVehicleForm(todayIso()),
	);
	// Bumped whenever priceEur is set from a new authoritative source (a parsed
	// listing URL or a picked catalogue candidate) so PriceFineTune's extras
	// anchor force-resets instead of only recentering when out of its old range.
	const [priceAnchorToken, setPriceAnchorToken] = useState(0);

	const [ppmvResult, setPpmvResult] = useState<PPMVResponse | null>(null);
	const [ppmvLoading, setPpmvLoading] = useState(false);
	const [ppmvApiError, setPpmvApiError] = useState<string | null>(null);

	const candidatesRef = useRef<HTMLDivElement>(null);
	const pricePanelRef = useRef<HTMLDivElement>(null);

	const validationOutcome = buildPpmvRequest(form);
	const validationError =
		typeof validationOutcome === "string" ? validationOutcome : null;
	const ppmvHint = validationError ?? ppmvApiError;

	function patchForm(patch: Partial<VehicleFormValues>) {
		setForm((prev) => ({ ...prev, ...patch }));
	}

	function applyCandidate(candidate: CatalogueCandidate) {
		setSelectedCatalogueId(candidate.catalogue_id);
		patchForm({
			priceEur: String(candidate.price_eur),
			co2: candidate.co2_g_km !== null ? String(candidate.co2_g_km) : form.co2,
			fuelType:
				candidate.fuel_type === "diesel" || candidate.fuel_type === "petrol"
					? candidate.fuel_type
					: form.fuelType,
		});
		setPriceAnchorToken((t) => t + 1);
		// Picking a candidate is the last step before the price/PPMV becomes
		// meaningful, so jump straight to it instead of leaving the user to
		// scroll past the rest of the form — but only when it isn't already on
		// screen. On desktop the price panel is a `lg:sticky` sidebar that's
		// pinned near the top of the viewport as soon as you've scrolled past
		// it once; calling scrollIntoView unconditionally there is actively
		// harmful, not a no-op — confirmed in testing that a sticky element's
		// scrollIntoView target is computed from its unstuck in-flow position,
		// not its current stuck position, so it yanks the whole page back up
		// to roughly where the panel would sit if it weren't sticky. On mobile
		// (not sticky, stacked below the form) it's genuinely off-screen and
		// still needs the scroll.
		const panel = pricePanelRef.current;
		if (panel) {
			const rect = panel.getBoundingClientRect();
			const alreadyVisible = rect.top < window.innerHeight && rect.bottom > 0;
			if (!alreadyVisible) {
				panel.scrollIntoView({ behavior: "smooth", block: "start" });
			}
		}
	}

	async function handleUrlSubmit(
		rawUrl: string,
		turnstileToken: string | null,
	) {
		setUrlLoading(true);
		setUrlError(null);
		setUrlResult(null);
		setSearchResult(null);
		setSelectedCatalogueId(null);
		try {
			const data = await calculateFromUrl(normalizeUrl(rawUrl), turnstileToken);
			setUrlResult(data);

			const parsed = data.parsed;
			const nothingParsed =
				!parsed.brand &&
				!parsed.model &&
				parsed.price_eur === null &&
				parsed.co2_g_km === null;
			if (nothingParsed) {
				setUrlError(
					"Nismo uspjeli pročitati podatke iz ovog oglasa — provjerite je li poveznica ispravna ili unesite podatke ručno u nastavku.",
				);
			}

			patchForm({
				priceEur:
					data.parsed.price_eur !== null ? String(data.parsed.price_eur) : "",
				co2: data.parsed.co2_g_km !== null ? String(data.parsed.co2_g_km) : "",
				fuelType: guessFuelType(data.parsed.fuel_type),
				regDate: toIsoDate(data.parsed.first_registration),
				seatCount:
					data.parsed.seat_count !== null ? String(data.parsed.seat_count) : "",
				isNew: data.parsed.is_new,
			});
			setPriceAnchorToken((t) => t + 1);

			// Candidates come back ranked best-first (see rank_candidates in
			// matching.py) — always preselect the top match so the price/CO2
			// panel is populated immediately, whether or not the backend was
			// confident enough to auto-accept it. The user can still pick a
			// different row from the list if the guess is wrong.
			if (data.candidates.length > 0) {
				applyCandidate(data.candidates[0]);
			}
		} catch (err) {
			setUrlError(describeUrlError(err));
		} finally {
			setUrlLoading(false);
		}
	}

	function handleSearchResult(result: CatalogueSearchResponse | null) {
		setSearchResult(result);
		setUrlResult(null);
		setSelectedCatalogueId(null);
	}

	// Once a listing has been parsed, guide the user down the page: first to
	// the candidate picker so they can confirm/correct the catalogue match, or
	// straight to the price panel if there's nothing to pick.
	useEffect(() => {
		if (!urlResult) return;
		const target =
			urlResult.candidates.length > 0
				? candidatesRef.current
				: pricePanelRef.current;
		const frame = requestAnimationFrame(() => {
			target?.scrollIntoView({ behavior: "smooth", block: "start" });
		});
		return () => cancelAnimationFrame(frame);
	}, [urlResult]);

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
				setPpmvApiError(describePpmvError(err));
			} finally {
				setPpmvLoading(false);
			}
		}, 350);

		return () => clearTimeout(timer);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [
		form.priceEur,
		form.co2,
		form.fuelType,
		form.regDate,
		form.declDate,
		form.seatCount,
		form.isNew,
	]);

	const candidates = urlResult?.candidates ?? searchResult?.candidates ?? [];
	const showCandidates = candidates.length > 0;

	return (
		<div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 sm:py-8 pb-20 lg:pb-8">
			<h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[var(--text)] mb-1">
				Izračun PPMV-a
			</h1>
			<p className="text-sm text-[var(--text-soft)] mb-5 max-w-2xl">
				Procijenite hrvatski posebni porez na motorna vozila (PPMV) — zalijepite
				link oglasa ili odaberite vozilo izravno iz baze podataka, a cijenu i
				CO2 uvijek možete naknadno fino podesiti.
			</p>

			<div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
				<div className="lg:col-span-2 space-y-4">
					<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm p-4">
						<div className="flex gap-1 mb-3 rounded-xl bg-[var(--surface-alt)] p-1 w-fit overflow-x-auto">
							<button
								type="button"
								onClick={() => setMode("link")}
								className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
									mode === "link"
										? "bg-[var(--surface)] text-[var(--primary)] shadow-sm"
										: "text-[var(--text-soft)]"
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

					{urlResult && (
						<ParsedFieldsCard
							parsed={urlResult.parsed}
							warnings={urlResult.warnings}
						/>
					)}

					{showCandidates && (
						<div ref={candidatesRef} className="scroll-mt-20">
							<CandidatesList
								candidates={candidates}
								selectedCatalogueId={selectedCatalogueId}
								onSelect={applyCandidate}
							/>
						</div>
					)}

					<VehicleForm values={form} onChange={patchForm} />
				</div>

				<div
					id="price-panel"
					ref={pricePanelRef}
					className="lg:sticky lg:top-24 space-y-4 scroll-mt-20"
				>
					<PriceFineTune
						priceEur={Number(form.priceEur) || 0}
						onChange={(price) => patchForm({ priceEur: String(price) })}
						anchorToken={priceAnchorToken}
					/>

					{ppmvResult ? (
						<>
							<PPMVBreakdownCard result={ppmvResult} updating={ppmvLoading} />
							<CarVerticalCard vin={urlResult?.parsed.vin} />
						</>
					) : (
						<div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--surface-alt)] px-5 py-6 text-sm text-[var(--text-soft)]">
							{ppmvHint ?? "Popunite podatke o vozilu za izračun PPMV-a."}
						</div>
					)}
				</div>
			</div>

			<MobilePriceBar
				result={ppmvResult}
				updating={ppmvLoading}
				hint={ppmvHint}
			/>
		</div>
	);
}
