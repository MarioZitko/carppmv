import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";

export const metadata: Metadata = {
	title: "Kako se izračunava PPMV",
	description:
		"Formula za PPMV: vrijednosna i ekološka komponenta, umanjenje za starost vozila i primjer izračuna s brojevima iz službenog primjera Carinske uprave.",
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

/** One line of the worked example. `note` holds the bracket detail, which is
 * too long to sit on the label line: an earlier version put it inline and the
 * label wrapped to two lines while the value wrapped between number and
 * currency. Value stays on one line (`whitespace-nowrap`) and never shrinks. */
function ExampleRow({
	label,
	note,
	value,
	strong = false,
}: {
	label: string;
	note?: string;
	value: string;
	strong?: boolean;
}) {
	return (
		<div className="flex items-start justify-between gap-6 py-2.5 border-b border-[var(--border)] last:border-b-0">
			<div className="min-w-0 space-y-0.5">
				<div
					className={
						strong
							? "font-semibold text-[var(--text)]"
							: "text-[var(--text-soft)]"
					}
				>
					{label}
				</div>
				{note ? (
					<div className="text-xs leading-snug text-[var(--text-soft)] opacity-80">
						{note}
					</div>
				) : null}
			</div>
			<span
				className={`shrink-0 whitespace-nowrap font-mono-tab tabular-nums ${
					strong
						? "font-semibold text-[var(--text)]"
						: "font-medium text-[var(--text)]"
				}`}
			>
				{value}
			</span>
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
					Cijela formula i primjer s brojevima iz službenog primjera Carinske
					uprave.
				</p>
			</header>

			<Section title="Dvije komponente: vrijednosna i ekološka">
				<p>
					PPMV se sastoji od dva zbroja koji daju iznos poreza za vozilo kao
					novo. Taj se iznos zatim umanjuje ako je vozilo rabljeno.
				</p>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">
							Vrijednosna komponenta (VN + PC)
						</span>{" "}
						ovisi o cijeni vozila. Cijena upada u jedan od 12 razreda, a porez je
						fiksni iznos za taj razred (VN) uvećan za postotak (PC) razlike
						između cijene vozila i donje granice razreda. Najjeftiniji razredi
						nose stopu 0%, najskuplji 17%.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Ekološka komponenta (ON + EN)
						</span>{" "}
						radi po istom principu, samo po emisiji CO2. Fiksni iznos za razred
						(ON) uvećava se za iznos po gramu (EN) iznad donje granice razreda.
						Tablice su odvojene za dizelska i za ostala vozila. Vozilo s CO2
						ispod prvog razreda tablice ne plaća ekološku komponentu.
					</li>
				</ul>
			</Section>

			<Section title="Koje tablice vrijede za vaše vozilo">
				<p>
					Uredba propisuje dva odvojena kompleta tablica. Vozila prvi put
					registrirana do 31. prosinca 2020. računaju se po NEDC tablicama, a
					vozila registrirana od 1. siječnja 2021. po WLTP tablicama. Granice
					razreda i iznosi u ta dva kompleta nisu isti brojevi s pomakom, nego
					zasebne tablice. Presudan je datum prve registracije, ne datum kupnje
					ili uvoza. Razlika između ta dva ciklusa mjerenja objašnjena je na
					stranici{" "}
					<Link
						href="/nedc-vs-wltp"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						NEDC ili WLTP
					</Link>
					.
				</p>
			</Section>

			<Section title="Umanjenje za starost vozila">
				<p>
					Vozilo koje se prvi put registrira kao novo plaća puni iznos. Za
					rabljeno vozilo iznos se množi postotkom iz tablice amortizacije u
					Pravilniku. Nekoliko točaka za orijentaciju: 96% u prvom mjesecu nakon
					prve registracije, 77% pri kraju prve godine, 65% nakon dvije godine,
					41,56% u rasponu od 57 do 60 mjeseci i 19,32% između 168 i 180 mjeseci.
					Nakon 180 mjeseci postotak se dodatno smanjuje za 0,6 postotnih bodova
					za svako navršeno razdoblje od 12 mjeseci, sve do 360 mjeseci, gdje
					prestaje padati.
				</p>
				<p>
					Starost se ne dobiva običnim oduzimanjem kalendarskih mjeseci. Mjesec
					je pun tek kad dan u mjesecu prijave dosegne dan prve registracije.
					Vozilo prvi put registrirano 17. kolovoza 2020., prijavljeno 10. srpnja
					2025., ima 58 punih mjeseci, a ne 59, jer 10. u mjesecu još nije
					doseglo 17.
				</p>
			</Section>

			<Section title="Umanjenja po vrsti vozila">
				<p>
					Prije nego se primijeni amortizacija, iznos za vozilo kao novo može se
					umanjiti ovisno o vrsti vozila. Kad se primjenjuje više umanjenja, ona
					se množe.
				</p>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">
							Električna vozila
						</span>{" "}
						ne plaćaju PPMV. Isto vrijedi za svako vozilo s emisijom 0 g/km.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Plug-in hibridi
						</span>{" "}
						dobivaju umanjenje u postotku koji je brojčano jednak dometu vožnje
						na struju u gradskoj vožnji (EAER city, u kilometrima), najviše 100%.
						Domet od 59 km znači umanjenje od 59%.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Vozila s više sjedala
						</span>
						: 8 sjedala znači polovicu iznosa, 9 i više sjedala četvrtinu.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">Kamperi</span>{" "}
						plaćaju 15% iznosa.
					</li>
				</ul>
			</Section>

			<Section title="Primjer: Audi A5 40 TDI">
				<p>
					Brojevi su iz službenog primjera Carinske uprave. Rabljeno dizelsko
					vozilo, registrirano prije 2021., dakle po NEDC tablicama.
				</p>
				<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm px-5 py-2 text-sm">
					<ExampleRow label="Cijena vozila kao novog" value="70.318,61 EUR" />
					<ExampleRow label="Emisija CO2 (NEDC)" value="136 g/km" />
					<ExampleRow label="Gorivo" value="Dizel" />
					<ExampleRow label="Prva registracija" value="17.08.2020." />
					<ExampleRow label="Datum prijave" value="10.07.2025." />
					<ExampleRow label="Starost vozila" value="58 mjeseci" />
				</div>

				<p className="pt-1">Izračun:</p>
				<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm px-5 py-2 text-sm">
					<ExampleRow
						label="Vrijednosna komponenta"
						note="Razred 66.361,41 do 72.997,54 EUR: VN 4.379,85 EUR + 15% od 3.957,20 EUR iznad donje granice"
						value="4.973,43 EUR"
					/>
					<ExampleRow
						label="Ekološka komponenta"
						note="Razred 120 do 140 g/km, dizel: ON 947,10 EUR + 152,63 EUR za svaki od 16 g/km iznad 120"
						value="3.389,18 EUR"
					/>
					<ExampleRow label="Iznos za vozilo kao novo" value="8.362,61 EUR" />
					<ExampleRow
						label="Amortizacija"
						note="58 mjeseci starosti, razred od 57 do 60 mjeseci"
						value="41,56 %"
					/>
					<ExampleRow label="PPMV" value="3.475,50 EUR" strong />
				</div>
				<p>
					Isti primjer možete provjeriti i u{" "}
					<Link
						href="/"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						kalkulatoru
					</Link>{" "}
					ručnim unosom ovih podataka.
				</p>
			</Section>

			<Section title="Gdje se porez prijavljuje i plaća">
				<p>
					Izračun je jedna stvar, prijava druga. Poreznu prijavu na obrascu PP-MV
					podnosite carinskom uredu nadležnom prema svom prebivalištu ili
					sjedištu, u roku od 15 dana od dana unosa vozila u Hrvatsku. Prijava se
					može predati i elektronički kroz sustav e-Građani, s vjerodajnicom
					značajne razine sigurnosti, pa rješenje i obavijesti stižu u korisnički
					pretinac.
				</p>
				<p>
					Bez potvrde da je PPMV plaćen vozilo se ne može registrirati, pa je
					prijava korak koji dolazi prije tehničkog pregleda i registracije.
					Redoslijed cijelog postupka opisan je u{" "}
					<Link
						href="/vodic-uvoz-njemacka"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						vodiču za uvoz auta iz Njemačke
					</Link>
					.
				</p>
			</Section>

			<Section title="Izvori">
				<ul className="list-disc pl-5 space-y-2">
					<li>
						Uredba o načinu izračuna i visinama sastavnica za izračun posebnog
						poreza na motorna vozila, NN 156/22 (
						<a
							href="https://narodne-novine.nn.hr/clanci/sluzbeni/2022_12_156_2525.html"
							target="_blank"
							rel="noopener noreferrer"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							narodne-novine.nn.hr
						</a>
						), tablice vrijednosne i ekološke komponente.
					</li>
					<li>
						Pravilnik o posebnom porezu na motorna vozila, pročišćeni tekst (
						<a
							href="https://www.cvh.hr/gradani/propisi-i-upute/pravilnici/zakon-o-posebnom-porezu-na-motorna-vozila/pravilnik-o-posebnom-porezu-na-motorna-vozila/"
							target="_blank"
							rel="noopener noreferrer"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							cvh.hr
						</a>
						), tablica amortizacije, pravilo brojanja mjeseci i obrazac PP-MV.
					</li>
					<li>
						Postupak oporezivanja motornih vozila i prijava kroz e-Građane (
						<a
							href="https://carina.gov.hr/pristup-informacijama/propisi-i-sporazumi/trosarinsko-postupanje/trosarinsko-oporezivanje-opce-informacije/posebni-porez-na-motorna-vozila-3714/3714"
							target="_blank"
							rel="noopener noreferrer"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							carina.gov.hr
						</a>
						).
					</li>
				</ul>
			</Section>

			<div className="pt-2">
				<CalculatorCta>Izračunajte PPMV za svoje vozilo</CalculatorCta>
			</div>
		</div>
	);
}
