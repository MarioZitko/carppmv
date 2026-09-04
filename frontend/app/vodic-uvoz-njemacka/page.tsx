import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";

export const metadata: Metadata = {
	title: "Vodič za uvoz automobila iz Njemačke",
	description:
		"Koraci uvoza auta iz Njemačke u Hrvatsku: pronalazak oglasa, provjera specifikacija i CO2, izračun PPMV-a, prijevoz, homologacija i registracija.",
	alternates: { canonical: "/vodic-uvoz-njemacka" },
};

function Step({
	n,
	title,
	children,
}: {
	n: number;
	title: string;
	children: React.ReactNode;
}) {
	return (
		<div className="flex gap-4">
			<div className="shrink-0 flex h-8 w-8 items-center justify-center rounded-full bg-[var(--primary-soft)] text-sm font-semibold text-[var(--primary)]">
				{n}
			</div>
			<div className="space-y-2 pb-2">
				<h3 className="text-base font-semibold text-[var(--text)]">{title}</h3>
				<div className="space-y-2 text-sm leading-relaxed text-[var(--text-soft)]">
					{children}
				</div>
			</div>
		</div>
	);
}

export default function GuideImportGermanyPage() {
	return (
		<div className="mx-auto max-w-3xl px-6 py-14 space-y-10">
			<header className="space-y-2">
				<h1 className="text-2xl font-bold text-[var(--text)]">
					Vodič za uvoz automobila iz Njemačke
				</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Njemačko tržište rabljenih vozila (mobile.de, AutoScout24, autobid.de) je
					najveće u Europi — evo koraka od odabira oglasa do registracije u
					Hrvatskoj.
				</p>
			</header>

			<section className="space-y-6">
				<Step n={1} title="Pronađite oglas">
					<p>
						mobile.de, AutoScout24 i autobid.de su najveće njemačke platforme za
						rabljena vozila. autobid.de je aukcijska platforma (uglavnom za
						registrirane trgovce) i CO2 vrijednost se prije prijave rijetko
						prikazuje u samom oglasu, dok mobile.de i AutoScout24 obično imaju
						potpunije tehničke podatke.
					</p>
				</Step>

				<Step n={2} title="Provjerite specifikacije i CO2 vrijednost">
					<p>
						Prije nego ozbiljno razmatrate oglas, provjerite cijenu, CO2 emisije,
						datum prve registracije i broj sjedala — to su podaci koji izravno
						ulaze u izračun PPMV-a. Ako oglas ne navodi CO2, potražite podatak u
						COC dokumentu vozila ili ga provjerite kod prodavača prije kupnje —
						pogrešna pretpostavka o CO2 vrijednosti je jedna od najčešćih grešaka
						kod procjene troška uvoza (vidi{" "}
						<Link
							href="/nedc-vs-wltp"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							NEDC vs. WLTP
						</Link>{" "}
						za to koja vrijednost vrijedi za koji datum registracije).
					</p>
				</Step>

				<Step n={3} title="Izračunajte PPMV">
					<p>
						Zalijepite link oglasa u{" "}
						<Link href="/" className="font-medium text-[var(--primary)] hover:underline">
							kalkulator
						</Link>{" "}
						— pokušat će pročitati potrebne podatke izravno s oglasa i dopuniti
						ono što nedostaje. Dobivena procjena vam govori koliko će vas uvoz
						koštati prije nego uopće krenete s dogovorom oko kupnje i prijevoza.
					</p>
				</Step>

				<Step n={4} title="Dogovorite prijevoz">
					<p>
						Vozilo do Hrvatske možete dovesti sami (uz privremene pločice/Zollkennzeichen
						ili već postojeću njemačku registraciju) ili unajmiti transportnu
						tvrtku koja prevozi vozila iz Njemačke prema Hrvatskoj. Trošak
						prijevoza nije uključen u PPMV izračun — dodajte ga zasebno u ukupni
						budžet uvoza.
					</p>
				</Step>

				<Step n={5} title="Provjerite homologaciju">
					<p>
						Da bi se vozilo moglo registrirati u Hrvatskoj, mora zadovoljavati
						homologacijske uvjete — za većinu vozila proizvedenih za EU tržište to
						nije prepreka, ali provjerite ima li vozilo sve što hrvatska
						registracija zahtijeva (npr. ispravan COC dokument, sukladnost s EU
						normama).
					</p>
				</Step>

				<Step n={6} title="Registrirajte vozilo">
					<p>
						Zadnji korak je prijava vozila Carinskoj upravi radi obračuna i plaćanja
						PPMV-a, nakon čega slijedi tehnički pregled i registracija kod ovlaštenog
						stanica za tehnički pregled. Iznos koji vam kalkulator prikaže je
						procjena — službeni iznos određuje Carinska uprava na temelju stvarno
						predane dokumentacije.
					</p>
				</Step>
			</section>

			<section className="space-y-3">
				<h2 className="text-lg font-semibold text-[var(--text)]">Česte greške</h2>
				<ul className="list-disc pl-5 space-y-2 text-sm leading-relaxed text-[var(--text-soft)]">
					<li>
						<span className="font-medium text-[var(--text)]">
							Pogrešna pretpostavka o CO2 vrijednosti.
						</span>{" "}
						Procjena &bdquo;na oko&rdquo; ili preuzimanje CO2 vrijednosti sličnog, ali ne
						identičnog modela može značajno promijeniti iznos PPMV-a — ekološka
						komponenta raste po razredima CO2, ne linearno cijelim rasponom.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Nedostajući ili neispravan COC dokument.
						</span>{" "}
						Bez COC dokumenta teško je potvrditi CO2 vrijednost i ostale
						tehničke podatke potrebne za registraciju — provjerite prije kupnje da
						ga prodavač uopće ima ili da ga može ishoditi.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Zaboravljen trošak prijevoza i tehničkog pregleda.
						</span>{" "}
						PPMV je samo jedna stavka ukupnog troška uvoza — prijevoz, tehnički
						pregled i registracijske pristojbe dolaze zasebno.
					</li>
				</ul>
			</section>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<p>
					Za detaljno objašnjenje same formule pogledajte{" "}
					<Link
						href="/kako-se-izracunava-ppmv"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						Kako se izračunava PPMV
					</Link>
					, a za odgovore na dodatna pitanja{" "}
					<Link
						href="/cesta-pitanja"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						Česta pitanja
					</Link>
					.
				</p>
			</section>

			<div className="pt-2">
				<CalculatorCta>Izračunajte PPMV za oglas koji ste pronašli</CalculatorCta>
			</div>
		</div>
	);
}
