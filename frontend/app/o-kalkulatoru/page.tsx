import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";

export const metadata: Metadata = {
	title: "O kalkulatoru",
	description:
		"Kako carPPMV računa posebni porez na motorna vozila, odakle dolaze podaci o vozilima i što alat namjerno ne radi.",
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
					Metoda, izvori podataka i granice alata.
				</p>
			</header>

			<Section title="Čemu služi">
				<p>
					carPPMV procjenjuje posebni porez na motorna vozila za auto koji
					planirate uvesti ili registrirati. Zalijepite poveznicu oglasa s
					mobile.de, AutoScout24, Njuškala ili autobid.de i alat pokušava
					pročitati marku, model, cijenu, emisiju CO2 i datum prve registracije,
					pa na temelju toga izračuna porez. Sve pročitano možete ispraviti ili
					dopuniti prije izračuna, a podatke možete unijeti i potpuno ručno.
				</p>
			</Section>

			<Section title="Odakle dolazi CO2 kad ga oglas ne navodi">
				<p>
					CO2 je podatak koji najčešće nedostaje. Alat tada pretražuje bazu
					izgrađenu iz službenih cjenika uvoznika koje objavljuje Carinska uprava
					i uspoređuje marku, model i izvedbu iz oglasa s redovima u toj bazi.
				</p>
				<p>
					Kad je podudaranje sigurno, CO2 se popuni sam. Kad nije, dobivate
					rangiranu listu kandidata i birate sami. To je namjerno: krivo pogođena
					cijena ili CO2 tiho pokvare cijeli izračun, dok prazno polje samo
					tražite da ga ispunite.
				</p>
				<p>
					Ako ni oglas ni baza nemaju CO2, alat nudi orijentacijski raspon
					sastavljen iz tehničkih tablica njemačke Wikipedije. Taj raspon nikad
					ne ulazi u izračun i služi za grubu provjeru dok ne pogledate COC
					dokument vozila.
				</p>
			</Section>

			<Section title="Izvori formule">
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">
							Uredba o načinu izračuna i visinama sastavnica za izračun posebnog
							poreza na motorna vozila
						</span>
						, NN 156/22. Iz nje dolaze tablice vrijednosne i ekološke komponente,
						odvojene za vozila registrirana prije i od 1.1.2021. Objavljena na{" "}
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
						</span>
						. Iz njega dolaze tablica amortizacije po starosti i pravilo brojanja
						punih mjeseci između prve registracije i dana prijave.
					</li>
				</ul>
				<p>
					Formula je prepisana iz tih propisa i provjerena na službenom primjeru
					Carinske uprave, koji je u cijelosti prikazan na stranici{" "}
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
					Ne podnosi poreznu prijavu, ne provjerava homologaciju i ne zamjenjuje
					porezno rješenje. Ne računa ni prijevoz, osiguranje, tehnički pregled
					ni registracijske pristojbe. Rezultat je procjena, a obvezujući iznos
					utvrđuje Carinska uprava na temelju predane dokumentacije.
				</p>
			</Section>

			<Section title="Tko ga radi">
				<p>
					Projekt vodi{" "}
					<a
						href="https://mariozitko.github.io"
						target="_blank"
						rel="noopener noreferrer"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						Mario Žitković
					</a>{" "}
					samostalno. Ako naiđete na krivi izračun ili oglas koji se ne čita
					ispravno, javite na{" "}
					<a
						href="mailto:mariozitkovic@gmail.com"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						mariozitkovic@gmail.com
					</a>
					.
				</p>
			</Section>

			<div className="pt-2">
				<CalculatorCta />
			</div>
		</div>
	);
}
