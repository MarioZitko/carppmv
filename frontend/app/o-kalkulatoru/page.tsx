import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";

export const metadata: Metadata = {
	title: "O kalkulatoru",
	description:
		"Kako kalkulatoruvoza.com izračunava PPMV, koje izvore koristi i zašto rezultat nije službeno porezno mišljenje.",
	alternates: { canonical: "/o-kalkulatoru" },
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

export default function AboutCalculatorPage() {
	return (
		<div className="mx-auto max-w-3xl px-6 py-14 space-y-10">
			<header className="space-y-2">
				<h1 className="text-2xl font-bold text-[var(--text)]">O kalkulatoru</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Metodologija, izvori i granice ovog alata.
				</p>
			</header>

			<Section title="Što kalkulator radi">
				<p>
					kalkulatoruvoza.com procjenjuje hrvatski posebni porez na motorna vozila
					(PPMV) za vozilo koje planirate uvesti. Zalijepite link oglasa (mobile.de,
					AutoScout24, njuškalo ili autobid.de) i alat pokuša pročitati potrebne
					podatke — marku, model, cijenu, CO2 emisije, datum prve registracije — te
					na temelju njih izračuna procjenu poreza. Sve što alat ne uspije pouzdano
					pročitati možete ručno unijeti ili ispraviti prije nego pogledate rezultat.
				</p>
			</Section>

			<Section title="Kako se popunjavaju podaci koji nedostaju u oglasu">
				<p>
					Najčešće nedostaje CO2 vrijednost — puno oglasa je jednostavno ne navodi.
					Kalkulator tada pretražuje internu bazu izgrađenu iz službenih cjenika
					uvoznika koje objavljuje Carinska uprava, uspoređujući marku, model i
					izvedbu vozila iz oglasa s redovima te baze. Kad je podudaranje dovoljno
					pouzdano, CO2 (i cijena kad je relevantna) se automatski popuni; kad nije,
					dobivate popis mogućih kandidata da sami odaberete pravi. Kao zadnju
					opciju, kad ni oglas ni baza ne daju CO2, alat nudi orijentacijski raspon
					prikupljen iz de.wikipedia.org tehničkih tablica — to je isključivo
					smjernica za usporedbu s COC dokumentom vozila, nikad se ne koristi
					automatski u samom poreznom izračunu.
				</p>
			</Section>

			<Section title="Formula i izvori">
				<p>
					Sam izračun poreza temelji se isključivo na javno dostupnim propisima:
				</p>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">
							Uredba o načinu izračuna i visinama sastavnica za izračun posebnog
							poreza na motorna vozila
						</span>{" "}
						(NN 156/22) — tablice vrijednosne (VN/PC) i ekološke (ON/EN)
						komponente, odvojene za vozila registrirana prije i poslije 1.1.2021.
						Izvor:{" "}
						<a
							href="https://narodne-novine.nn.hr/clanci/sluzbeni/2022_12_156_2525.html"
							target="_blank"
							rel="noopener noreferrer"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							narodne-novine.nn.hr
						</a>
						.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Pravilnik o posebnom porezu na motorna vozila
						</span>{" "}
						— tablica amortizacije po starosti vozila i pravilo brojanja punih
						mjeseci između datuma prve registracije i deklaracije.
					</li>
				</ul>
				<p>
					Puni prikaz formule s objašnjenjem svakog koraka, uključujući stvaran
					primjer izračuna, nalazi se na stranici{" "}
					<Link
						href="/kako-se-izracunava-ppmv"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						Kako se izračunava PPMV
					</Link>
					.
				</p>
			</Section>

			<Section title="Što alat ne radi">
				<p>
					Kalkulator ne podnosi carinsku deklaraciju, ne provjerava homologaciju
					vozila i ne zamjenjuje službeno porezno rješenje Carinske uprave. Rezultat
					je procjena — konačan iznos određuje isključivo nadležno tijelo na temelju
					stvarno predane dokumentacije.
				</p>
			</Section>

			<div className="pt-2">
				<CalculatorCta />
			</div>
		</div>
	);
}
