import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";
import { FaqList, FaqSchema, type FaqItem } from "@/components/Faq";

export const metadata: Metadata = {
	title: "NEDC vs. WLTP — koji CO2 vrijedi za PPMV",
	description:
		"Razlika između NEDC i WLTP mjerenja CO2, zašto je datum 1.1.2021. presudan za izračun PPMV-a i gdje pronaći ispravnu vrijednost za svoje vozilo.",
	alternates: { canonical: "/nedc-vs-wltp" },
};

const FAQ_ITEMS: FaqItem[] = [
	{
		question: "Koji datum je bitan — datum proizvodnje ili datum registracije?",
		answer:
			"Datum prve registracije vozila, ne datum proizvodnje. Vozilo proizvedeno krajem 2020. ali registrirano tek u 2021. već potpada pod WLTP tablice u ovom kalkulatoru.",
	},
	{
		question: "Što ako oglas navodi i NEDC i WLTP vrijednost CO2?",
		answer:
			"Koristite vrijednost koja odgovara ciklusu za datum prve registracije vozila — NEDC za registraciju prije 1.1.2021, WLTP za registraciju od tog datuma nadalje. To je vrijednost koja se stvarno nalazi u COC dokumentu vozila.",
	},
	{
		question: "Zašto se WLTP vrijednosti CO2 čine više od NEDC vrijednosti za isto vozilo?",
		answer:
			"WLTP ciklus mjeri u realističnijim uvjetima vožnje (veće brzine, dulje dionice, manje idealizirano ubrzanje) pa za isto vozilo obično daje veći broj g/km CO2 nego stariji NEDC ciklus. Zato tablice u Uredbi za WLTP-registrirana vozila imaju i drugačije (pomaknute) granice bodovnih razreda.",
	},
];

export default function NedcVsWltpPage() {
	return (
		<div className="mx-auto max-w-3xl px-6 py-14 space-y-10">
			<header className="space-y-2">
				<h1 className="text-2xl font-bold text-[var(--text)]">
					NEDC vs. WLTP — koji CO2 vrijedi za PPMV
				</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Dva ciklusa mjerenja, dvije različite porezne tablice — evo kako znati
					koji se primjenjuje na vaše vozilo.
				</p>
			</header>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">Što je NEDC</h2>
				<p>
					NEDC (New European Driving Cycle) je stariji europski ciklus mjerenja
					potrošnje goriva i emisija CO2, korišten za homologaciju vozila do kraja
					2020. Mjerenja su se provodila u laboratorijskim uvjetima s relativno
					blagim profilom ubrzanja i niskim brzinama, zbog čega su izmjerene
					vrijednosti CO2 sustavno niže od stvarne potrošnje u svakodnevnoj vožnji.
				</p>
			</section>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">Što je WLTP</h2>
				<p>
					WLTP (Worldwide Harmonised Light Vehicle Test Procedure) je noviji ciklus
					koji je zamijenio NEDC — uključuje veće brzine, dulje testne dionice,
					realističniji profil ubrzanja i uzima u obzir dodatnu opremu vozila. Zbog
					toga WLTP vrijednosti CO2 za isto vozilo obično ispadaju više od starih
					NEDC vrijednosti, iako je stvarna potrošnja vozila ostala ista — mijenja
					se samo metoda mjerenja.
				</p>
			</section>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Datum 1.1.2021. i zašto je presudan za PPMV
				</h2>
				<p>
					Uredba o načinu izračuna PPMV-a (NN 156/22) propisuje dva odvojena
					seta tablica ekološke komponente (ON/EN) i vrijednosne komponente
					(VN/PC) — jedan za vozila prvi put registrirana do 31.12.2020., temeljen
					na NEDC vrijednostima CO2, i drugi za vozila registrirana od 1.1.2021.
					nadalje, temeljen na WLTP vrijednostima. Granice CO2 razreda i iznosi u
					te dvije tablice nisu isti brojevi pomaknuti za razliku ciklusa — riječ
					je o potpuno zasebnim tablicama, pa je bitno koristiti onu koja odgovara
					datumu prve registracije vozila, ne datumu kupnje ili uvoza.
				</p>
				<p>
					kalkulatoruvoza.com ovo automatski prepoznaje — čim unesete datum prve
					registracije, sam odabere ispravan set tablica za izračun.
				</p>
			</section>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Gdje pronaći CO2 vrijednost svog vozila
				</h2>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">COC dokument</span>{" "}
						(Certificate of Conformity) — najpouzdaniji izvor, sadrži točnu CO2
						vrijednost prema ciklusu koji vrijedi za taj model.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">Sam oglas</span> —
						većina oglasa na mobile.de, AutoScout24 i sličnim stranicama navodi
						CO2 vrijednost u tehničkim podacima vozila.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							kalkulatoruvoza.com
						</span>{" "}
						— kad oglas ne navodi CO2, kalkulator ga pokuša pronaći u internoj
						bazi službenih cjenika Carinske uprave, a kao zadnju opciju nudi
						orijentacijski raspon s Wikipedije, koji ipak uvijek treba usporediti
						sa stvarnim COC dokumentom.
					</li>
				</ul>
			</section>

			<section className="space-y-3">
				<h2 className="text-lg font-semibold text-[var(--text)]">Česta pitanja</h2>
				<FaqList items={FAQ_ITEMS} />
			</section>
			<FaqSchema items={FAQ_ITEMS} />

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<p>
					Za puni prikaz formule i primjer stvarnog izračuna pogledajte{" "}
					<Link
						href="/kako-se-izracunava-ppmv"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						Kako se izračunava PPMV
					</Link>
					.
				</p>
			</section>

			<div className="pt-2">
				<CalculatorCta>Unesite datum registracije i CO2 u kalkulator</CalculatorCta>
			</div>
		</div>
	);
}
