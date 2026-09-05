"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { UrlInputForm } from "@/components/UrlInputForm";
import { CatalogueSearchForm } from "@/components/CatalogueSearchForm";
import { CandidatesList } from "@/components/CandidatesList";
import { VehicleForm } from "@/components/VehicleForm";
import { PriceFineTune } from "@/components/PriceFineTune";
import { MobilePriceBar } from "@/components/MobilePriceBar";
import { PPMVBreakdownCard } from "@/components/PPMVBreakdownCard";
import { CarVerticalCard } from "@/components/CarVerticalCard";
import { ParsedFieldsCard } from "@/components/ParsedFieldsCard";
import {
	ApiTimeoutError,
	calculateFromUrl,
	calculateFromSpecs,
} from "@/lib/api";
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
	if (err instanceof ApiTimeoutError) {
		return "Dohvat oglasa predugo traje i poslužitelj ne odgovara. Pokušajte ponovno za trenutak ili unesite podatke ručno u nastavku.";
	}
	if (!(err instanceof ApiError)) {
		return "Nismo se uspjeli povezati s poslužiteljem. Provjerite internetsku vezu i pokušajte ponovno.";
	}
	switch (err.status) {
		case 429:
			return "Previše zahtjeva s ove adrese. Pričekajte nekoliko minuta pa pokušajte ponovno.";
		case 403:
			return "Sigurnosna provjera nije uspjela. Osvježite stranicu i zalijepite poveznicu ponovno.";
		case 503:
			return "Dnevni limit automatskog dohvata oglasa je dostignut. Unesite podatke o vozilu ručno u nastavku.";
		case 422:
			return "Ne prepoznajemo ovu poveznicu. Provjerite vodi li na oglas s podržane stranice (mobile.de, AutoScout24, autobid.de, Njuškalo) ili unesite podatke ručno u nastavku.";
		case 404:
			return "Oglas nije pronađen. Možda je uklonjen ili je poveznica netočna. Unesite podatke ručno u nastavku.";
		case 502:
		case 504:
			return "Stranica oglasa trenutno nije dostupna. Oglas je možda uklonjen ili istekao. Unesite podatke ručno u nastavku.";
		case 400:
			return "Podaci iz oglasa (cijena ili CO2) izgledaju neispravni pa izračun nije moguć. Provjerite oglas ili unesite podatke ručno u nastavku.";
		default:
			return "Čitanje oglasa nije uspjelo. Pokušajte ponovno ili unesite podatke ručno u nastavku.";
	}
}

// Same idea for the manual vehicle-data form — the engine's validation
// errors (out-of-range price/CO2 brackets) are also written in English for
// logs, so translate them into something an average user can act on.
function describePpmvError(err: unknown): string {
	if (err instanceof ApiTimeoutError) {
		return "Izračun predugo traje i poslužitelj ne odgovara. Pokušajte ponovno za trenutak.";
	}
	if (!(err instanceof ApiError)) {
		return "Izračun trenutno nije dostupan. Pokušajte ponovno za trenutak.";
	}
	if (err.status === 400) {
		return "Unesena cijena ili CO2 vrijednost je izvan očekivanog raspona. Provjerite jesu li podaci točni.";
	}
	return "Izračun trenutno nije dostupan. Pokušajte ponovno za trenutak.";
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

	function applyCandidate(
		candidate: CatalogueCandidate,
		scroll = true,
		// Set by the auto-preselect below when the backend returned a Wikipedia
		// CO2 hint. A hint means neither the listing nor an accepted catalogue
		// match produced a CO2 value, so silently filling the field from an
		// *unconfirmed* candidate would contradict the note sitting right under
		// it ("we don't know this — check your COC") with a number that looks
		// like we do. Price and fuel still apply: those are the candidate's
		// real contribution and are not what the hint is about. An explicit
		// click on a row is the user's own decision and always fills CO2.
		skipCo2 = false,
	) {
		setSelectedCatalogueId(candidate.catalogue_id);
		// Keys are omitted rather than set back to their current value: `form`
		// is captured from the render that created this closure, and
		// handleUrlSubmit calls patchForm immediately before this, so reading
		// `form.co2`/`form.fuelType` here would write a stale value back over
		// the patch that just landed.
		const patch: Partial<VehicleFormValues> = {
			priceEur: String(candidate.price_eur),
		};
		if (!skipCo2 && candidate.co2_g_km !== null) {
			patch.co2 = String(candidate.co2_g_km);
		}
		if (candidate.fuel_type === "diesel" || candidate.fuel_type === "petrol") {
			patch.fuelType = candidate.fuel_type;
		}
		patchForm(patch);
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
		//
		// `scroll=false` is passed by handleUrlSubmit's auto-preselect of the
		// top candidate — that path already has its own scroll (the urlResult
		// effect below, which targets candidatesRef so the user lands on the
		// picker first) and firing this scroll too raced it to a different
		// target on the same submit.
		if (!scroll) return;
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
					"Nismo uspjeli pročitati podatke iz ovog oglasa. Provjerite je li poveznica ispravna ili unesite podatke ručno u nastavku.",
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
				applyCandidate(data.candidates[0], false, data.wikipedia_hint !== null);
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

	// Which brand (and text) the Wikipedia engine picker should open on. Not a
	// precondition for opening it — with nothing known it starts at its own
	// brand list — only a way to skip the steps we can already answer.
	//
	// A parsed listing is the better seed when there is one: it is the actual
	// car, whereas a catalogue row is at best a confirmed match to it and at
	// worst an unconfirmed top-ranked guess. But the catalogue path is worth
	// seeding from too — in "Pretraži bazu vozila" mode there is no listing at
	// all, and the row the user selected is then the only statement of what the
	// car is that we have.
	const selectedCandidate =
		candidates.find((c) => c.catalogue_id === selectedCatalogueId) ??
		candidates[0];
	const co2Lookup = urlResult?.parsed.brand
		? {
				brand: urlResult.parsed.brand,
				query: [urlResult.parsed.model, urlResult.parsed.variant]
					.filter(Boolean)
					.join(" "),
			}
		: selectedCandidate
			? {
					brand: selectedCandidate.brand,
					query: [selectedCandidate.model, selectedCandidate.variant]
						.filter(Boolean)
						.join(" "),
				}
			: null;

	return (
		<div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 sm:py-8 pb-20 lg:pb-8">
			<h1 className="text-xl sm:text-2xl font-bold tracking-tight text-[var(--text)] mb-1">
				Izračun PPMV-a
			</h1>
			<p className="text-sm text-[var(--text-soft)] mb-5 max-w-2xl">
				Procijenite posebni porez na motorna vozila. Zalijepite poveznicu oglasa
				ili odaberite vozilo iz baze, a cijenu i CO2 možete naknadno podesiti.
			</p>

			<div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
				<div className="lg:col-span-2 space-y-4">
					<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm p-4">
						<div className="flex gap-1 mb-3 rounded-xl bg-[var(--surface-alt)] p-1 w-fit overflow-x-auto">
							<button
								type="button"
								onClick={() => setMode("link")}
								className={`rounded-lg px-4 py-1.5 min-h-11 text-sm font-medium transition-colors ${
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
								className={`rounded-lg px-4 py-1.5 min-h-11 text-sm font-medium transition-colors ${
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

					<VehicleForm
						values={form}
						onChange={patchForm}
						co2Hint={urlResult?.wikipedia_hint}
						co2Lookup={co2Lookup}
					/>
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

					<PPMVBreakdownCard
						result={ppmvResult}
						updating={ppmvLoading}
						hint={ppmvHint ?? "Popunite podatke o vozilu za izračun PPMV-a."}
					/>
				</div>
			</div>

			<div className="mt-4">
				<CarVerticalCard vin={urlResult?.parsed.vin} />
			</div>

			{/* Deliberately short: the long "how it works" and FAQ copy lives on
			    /o-kalkulatoru and /cesta-pitanja, so it isn't duplicated across two
			    URLs. What stays here is unique to this page and keeps the landing
			    page from being a bare form with no context. */}
			<section className="mt-12 max-w-3xl space-y-3">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Što ovaj kalkulator računa
				</h2>
				<div className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
					<p>
						Posebni porez na motorna vozila (PPMV) plaća se prije prve
						registracije vozila u Hrvatskoj. Iznos ovisi o cijeni vozila,
						emisiji CO2 i starosti vozila, a računa se po tablicama iz Uredbe NN
						156/22 i Pravilnika o posebnom porezu na motorna vozila. Iste
						tablice koristi i ovaj kalkulator.
					</p>
					<p>
						Zalijepite poveznicu oglasa i kalkulator pokušava sam pročitati
						cijenu, CO2 i datum prve registracije. Podatak koji nedostaje,
						najčešće je to CO2, traži u bazi službenih cjenika uvoznika. Sve
						možete i ručno ispraviti prije izračuna.
					</p>
					<p className="flex flex-wrap gap-x-4 gap-y-1">
						<Link
							href="/kako-se-izracunava-ppmv"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							Cijela formula s primjerom izračuna
						</Link>
						<Link
							href="/vodic-uvoz-njemacka"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							Svi koraci uvoza iz Njemačke
						</Link>
						<Link
							href="/cesta-pitanja"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							Česta pitanja
						</Link>
					</p>
				</div>
			</section>

			<MobilePriceBar
				result={ppmvResult}
				updating={ppmvLoading}
				hint={ppmvHint}
			/>
		</div>
	);
}
