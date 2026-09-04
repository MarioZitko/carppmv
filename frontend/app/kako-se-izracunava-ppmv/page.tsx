import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";

export const metadata: Metadata = {
	title: "Kako se izračunava PPMV",
	description:
		"Formula za PPMV korak po korak — vrijednosna i ekološka komponenta, amortizacija po starosti vozila, i stvaran primjer izračuna za Audi A5.",
	alternates: { canonical: "/kako-se-izracunava-ppmv" },
};

function Section({
	title,
	children,
}: {
	title: string;
	children: React.ReactNode;
}) {
	return (
		<section className="space-y-3">
			<h2 className="text-lg font-semibold text-[var(--text)]">{title}</h2>
			<div className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				{children}
			</div>
		</section>
	);
}

function ExampleRow({ label, value }: { label: string; value: string }) {
	return (
		<div className="flex items-baseline justify-between gap-4 py-1.5 border-b border-[var(--border)] last:border-b-0">
			<span className="text-[var(--text-soft)]">{label}</span>
			<span className="font-mono-tab font-medium text-[var(--text)]">{value}</span>
		</div>
	);
}

export default function HowPpmvIsCalculatedPage() {
	return (
		<div className="mx-auto max-w-3xl px-6 py-14 space-y-10">
			<header className="space-y-2">
				<h1 className="text-2xl font-bold text-[var(--text)]">
					Kako se izračunava PPMV
				</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Puna formula, korak po korak, s pravim brojevima iz službenog primjera
					Carinske uprave.
				</p>
			</header>

			<Section title="Formula u osnovi: VN + PC + ON + EN">
				<p>
					PPMV se računa iz dvije komponente koje se zbrajaju u „vrijednost novog
					vozila” (as-new iznos), a zatim umanjuju za starost vozila:
				</p>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">
							Vrijednosna komponenta (VN + PC)
						</span>{" "}
						— fiksni iznos (VN) plus postotak (PC) razlike između cijene vozila i
						donje granice razreda u koji cijena upada. Raste s cijenom vozila kroz
						12 razreda, od 0% za vozila do 13.272,28 EUR do 17% za vozila iznad
						79.633,69 EUR.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Ekološka komponenta (ON + EN)
						</span>{" "}
						— isti princip, ali po CO2 emisiji umjesto cijene: fiksni iznos (ON)
						plus stopa po gramu CO2 (EN) iznad donje granice razreda. Vozila s CO2
						ispod najniže granice tablice (npr. čisti hibridi, vrlo niska
						potrošnja) ne plaćaju ekološku komponentu.
					</li>
				</ul>
				<p>
					Zbroj te dvije komponente je iznos koji bi vozilo plaćalo kao novo. Za
					rabljena vozila taj se iznos zatim množi s postotkom amortizacije prema
					starosti vozila.
				</p>
			</Section>

			<Section title="NEDC ili WLTP tablica — ovisi o datumu registracije">
				<p>
					Postoje dva odvojena para tablica (vrijednosna + ekološka): jedan za
					vozila prvi put registrirana do 31.12.2020. (NEDC), drugi za vozila
					registrirana od 1.1.2021. (WLTP). Granice CO2 razreda i iznosi se
					razlikuju između te dvije tablice — nije riječ o istim brojevima s
					pomakom. Puno objašnjenje razlike i zašto WLTP vrijednosti CO2 ispadnu
					više za isto vozilo pročitajte na{" "}
					<Link
						href="/nedc-vs-wltp"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						stranici NEDC vs. WLTP
					</Link>
					.
				</p>
			</Section>

			<Section title="Amortizacija po starosti vozila">
				<p>
					Rabljena vozila plaćaju postotak od iznosa „kao novo”, prema Pravilniku o
					posebnom porezu na motorna vozila. Novo vozilo (0 mjeseci starosti)
					plaća 96% već u prvom mjesecu, a postotak dalje pada — sporije s
					vremenom — sve do 168-180 mjeseci starosti (oko 14-15 godina), kad
					iznosi 19,32%. Nakon 180 mjeseci postotak se dodatno smanjuje za 0,6
					postotnih bodova za svako navršeno razdoblje od 12 mjeseci, do najviše
					360 mjeseci starosti, gdje se zamrzava.
				</p>
				<p>
					Starost vozila se ne računa naivno oduzimanjem kalendarskih mjeseci —
					mjesec se smatra punim tek kad dan u mjesecu deklaracije dosegne (ili
					prijeđe) dan u mjesecu prve registracije. Vozilo registrirano
					17.08.2020., prijavljeno 10.07.2025., ima točno 58 punih mjeseci — ne
					59, jer 10. u srpnju još nije dosegnulo 17., dan kad bi se 59. mjesec
					smatrao punim.
				</p>
			</Section>

			<Section title="Umanjenja za tip vozila">
				<p>
					Prije amortizacije, iznos „kao novo” može se dodatno umanjiti ovisno o
					tipu vozila — sva umanjenja se međusobno množe kad ih je više
					primjenjivo:
				</p>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">
							Električna vozila
						</span>{" "}
						— potpuno oslobođena PPMV-a (0 EUR).
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Plug-in hibridi
						</span>{" "}
						— umanjenje u postotku jednakom dometu vožnje isključivo na struju
						(EAER city domet u km, najviše 100%).
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Vozila s 8 sjedala
						</span>{" "}
						plaćaju polovicu (×0,50), s 9 i više sjedala četvrtinu (×0,25) iznosa.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">Kamperi</span>{" "}
						plaćaju 15% iznosa (umanjenje ×0,15).
					</li>
				</ul>
			</Section>

			<Section title="Stvaran primjer: Audi A5 40 TDI">
				<p>
					Primjer je preuzet iz stvarnog rješenja Carinske uprave (NEDC, dizel,
					rabljeno vozilo):
				</p>
				<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm px-5 py-4 text-sm">
					<ExampleRow label="Cijena vozila (kao novo)" value="70.318,61 EUR" />
					<ExampleRow label="CO2 emisija (NEDC)" value="136 g/km" />
					<ExampleRow label="Gorivo" value="Dizel" />
					<ExampleRow label="Prva registracija" value="17.08.2020." />
					<ExampleRow label="Datum deklaracije" value="10.07.2025." />
					<ExampleRow label="Starost vozila" value="58 mjeseci" />
				</div>
				<p className="pt-1">Izračun po koracima:</p>
				<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm px-5 py-4 text-sm">
					<ExampleRow
						label="Vrijednosna komponenta (razred 66.361,41–72.997,54 EUR: VN 4.379,85 + 15% iznad donje granice)"
						value="4.973,43 EUR"
					/>
					<ExampleRow
						label="Ekološka komponenta (razred 120–140 g/km: ON 947,10 + 152,63 EUR/g iznad 120 g/km)"
						value="3.389,18 EUR"
					/>
					<ExampleRow label="Ukupno kao novo (VN+PC + ON+EN)" value="8.362,61 EUR" />
					<ExampleRow label="Amortizacija za 58 mjeseci starosti" value="41,56 %" />
					<ExampleRow label="PPMV" value="3.475,50 EUR" />
				</div>
				<p>
					Isti primjer, s istim brojevima, možete provjeriti i u{" "}
					<Link href="/" className="font-medium text-[var(--primary)] hover:underline">
						kalkulatoru
					</Link>{" "}
					unosom ovih podataka ručno.
				</p>
			</Section>

			<Section title="Izvori">
				<ul className="list-disc pl-5 space-y-2">
					<li>
						Uredba o načinu izračuna i visinama sastavnica za izračun posebnog
						poreza na motorna vozila (NN 156/22) —{" "}
						<a
							href="https://narodne-novine.nn.hr/clanci/sluzbeni/2022_12_156_2525.html"
							target="_blank"
							rel="noopener noreferrer"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							narodne-novine.nn.hr
						</a>
					</li>
					<li>
						Pravilnik o posebnom porezu na motorna vozila — pročišćeni tekst,{" "}
						<a
							href="https://carina.gov.hr"
							target="_blank"
							rel="noopener noreferrer"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							carina.gov.hr
						</a>
					</li>
				</ul>
			</Section>

			<div className="pt-2">
				<CalculatorCta>Izračunajte PPMV za svoje vozilo</CalculatorCta>
			</div>
		</div>
	);
}
