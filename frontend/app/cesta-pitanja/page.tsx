import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";
import { FaqList, FaqSchema, type FaqItem } from "@/components/Faq";

export const metadata: Metadata = {
	title: "Česta pitanja o PPMV-u i uvozu vozila",
	description:
		"Odgovori na najčešća pitanja o PPMV-u, CO2 vrijednostima, NEDC/WLTP tablicama, umanjenjima i tome kako kalkulatoruvoza.com radi.",
	alternates: { canonical: "/cesta-pitanja" },
};

const FAQ_ITEMS: FaqItem[] = [
	{
		question: "Što je PPMV?",
		answer:
			"Posebni porez na motorna vozila (PPMV) plaća se pri prvoj registraciji vozila u Hrvatskoj. Iznos ovisi o vrijednosti vozila (VN/PC komponenta) i njegovim CO2 emisijama (ON/EN komponenta), uz umanjenje za starost vozila prema propisanoj tablici amortizacije.",
	},
	{
		question: "Trebam li platiti PPMV ako uvozim vozilo iz EU?",
		answer:
			"Da. PPMV je nacionalni porez na registraciju vozila i plaća se bez obzira odakle vozilo dolazi — iz EU ili izvan nje. Carinska pristojba i PDV su druga priča: te se stavke naplaćuju samo pri uvozu iz zemalja izvan EU, budući da unutar jedinstvenog tržišta EU nema carine.",
	},
	{
		question: "Plaćam li PPMV i za novo i za rabljeno vozilo?",
		answer:
			"Da, oboje podliježe PPMV-u. Razlika je u amortizaciji: novo vozilo plaća pun iznos (faktor 1,0), dok se rabljenom vozilu iznos umanjuje prema propisanoj tablici koja ovisi o starosti u mjesecima od prve registracije.",
	},
	{
		question: "Je li ovo službeni izračun?",
		answer:
			"Ne. Ovo je procjena temeljena na javno dostupnim propisima (Uredbi o načinu izračuna PPMV-a, NN 156/22, i Pravilniku o posebnom porezu na motorna vozila) — nije službeno porezno mišljenje. Za konačan, obvezujući iznos obratite se Carinskoj upravi.",
	},
	{
		question: "Kako kalkulator izračunava iznos?",
		answer: (
			<>
				Prema formuli propisanoj Uredbom — zbroj vrijednosne i ekološke komponente,
				umanjen za amortizaciju po starosti vozila. Puni prikaz svakog koraka, s
				pravim primjerom izračuna, nalazi se na stranici{" "}
				<Link
					href="/kako-se-izracunava-ppmv"
					className="font-medium text-[var(--primary)] hover:underline"
				>
					Kako se izračunava PPMV
				</Link>
				.
			</>
		),
		answerText:
			"Prema formuli propisanoj Uredbom — zbroj vrijednosne i ekološke komponente, umanjen za amortizaciju po starosti vozila.",
	},
	{
		question: "Koja je razlika između NEDC i WLTP mjerenja CO2?",
		answer: (
			<>
				Riječ je o dva različita ciklusa mjerenja potrošnje i emisija — primjenjuju se
				različite porezne tablice ovisno o tome je li vozilo prvi put registrirano
				prije ili poslije 1.1.2021. Puno objašnjenje s primjerima pročitajte na
				stranici{" "}
				<Link href="/nedc-vs-wltp" className="font-medium text-[var(--primary)] hover:underline">
					NEDC vs. WLTP
				</Link>
				.
			</>
		),
		answerText:
			"Riječ je o dva različita ciklusa mjerenja potrošnje i emisija — primjenjuju se različite porezne tablice ovisno o tome je li vozilo prvi put registrirano prije ili poslije 1.1.2021.",
	},
	{
		question: "Odakle da znam CO2 vrijednost svog vozila?",
		answer:
			"Najpouzdaniji izvor je COC dokument (Certificate of Conformity) vozila. Kad zalijepite link oglasa, kalkulator prvo pokuša pročitati CO2 izravno s oglasa; ako ga nema, pretražuje internu bazu službenih cjenika Carinske uprave po marki, modelu i izvedbi. Kad ni to ne uspije, nudi orijentacijski raspon prikupljen s Wikipedije — to je samo smjernica za usporedbu s COC dokumentom, nikad se automatski ne koristi u samom izračunu.",
	},
	{
		question: "Koliko je pouzdana Wikipedia procjena CO2?",
		answer:
			"Namjerno je označena kao orijentacijska, ne kao ulazni podatak za izračun — CO2 polje u obrascu se njome nikad ne popunjava automatski. Uvijek je usporedite sa stvarnim COC dokumentom prije nego što se na nju oslonite.",
	},
	{
		question: "S kojih stranica kalkulator može pročitati oglas?",
		answer:
			"Podržani su mobile.de, AutoScout24, njuškalo i autobid.de. Zalijepite link oglasa i kalkulator će pokušati pročitati marku, model, cijenu, CO2 i ostale podatke izravno s oglasa.",
	},
	{
		question: "Što ako link oglasa ne radi ili nešto ne uspije pročitati?",
		answer:
			"Podatke uvijek možete unijeti ručno — ispod obrasca za link nalazi se i opcija pretrage naše baze vozila, a polja za cijenu, CO2, datum registracije i ostalo možete i sami popuniti ili ispraviti u bilo kojem trenutku.",
	},
	{
		question: "Kalkulator mi je ponudio nekoliko mogućih vozila iz baze — koje odabrati?",
		answer:
			"Kad kalkulator nije dovoljno siguran koji red iz baze cjenika odgovara oglasu, prikazuje rangiranu listu kandidata umjesto da nagađa — to je namjerno, jer bi pogrešno automatski odabrana cijena ili CO2 vrijednost pokvarila cijeli izračun. Odaberite red koji najbolje odgovara izvedbi vozila iz oglasa (motor, snaga, godina).",
	},
	{
		question: "Postoji li olakšica za električna vozila?",
		answer:
			"Da, električna vozila su u potpunosti oslobođena PPMV-a (iznos je 0 EUR).",
	},
	{
		question: "Postoji li olakšica za plug-in hibride?",
		answer:
			"Da, umanjenje se računa prema dometu vožnje isključivo na struju (EAER city domet u kilometrima) — što je taj domet veći, umanjenje je veće, do najviše 100%.",
	},
	{
		question: "Postoji li olakšica za vozila s više sjedala ili kampere?",
		answer:
			"Da. Vozila s ukupno 8 sjedala plaćaju polovicu iznosa, s 9 i više sjedala četvrtinu. Kamperi plaćaju 15% iznosa. Sva umanjenja se primjenjuju automatski kad u obrascu označite relevantno polje.",
	},
	{
		question: "Je li trošak prijevoza uključen u izračun?",
		answer: (
			<>
				Ne. Kalkulator izračunava isključivo PPMV. Trošak prijevoza, tehničkog
				pregleda i registracijskih pristojbi dolazi zasebno — pogledajte{" "}
				<Link
					href="/vodic-uvoz-njemacka"
					className="font-medium text-[var(--primary)] hover:underline"
				>
					Vodič za uvoz automobila iz Njemačke
				</Link>{" "}
				za pregled svih koraka i troškova uvoza.
			</>
		),
		answerText:
			"Ne. Kalkulator izračunava isključivo PPMV. Trošak prijevoza, tehničkog pregleda i registracijskih pristojbi dolazi zasebno.",
	},
	{
		question: "Je li korištenje kalkulatora besplatno?",
		answer: "Da, kalkulator je u potpunosti besplatan i ne zahtijeva registraciju.",
	},
	{
		question: "Što je carVertical link koji vidim na stranici?",
		answer:
			"To je partnerski (affiliate) link prema carVertical, servisu za provjeru povijesti vozila po VIN broju ili registarskoj oznaci. Ako kliknete na njega i kupite provjeru, kalkulatoruvoza.com može dobiti proviziju — vas to ništa dodatno ne košta.",
	},
	{
		question: "Koje podatke kalkulator prikuplja o meni?",
		answer: (
			<>
				Kalkulator ne zahtijeva registraciju i može se koristiti anonimno. Detalje
				o tome koji se podaci u pozadini ipak obrađuju (npr. hashirana IP adresa
				radi sprječavanja zlouporabe) pogledajte na stranici{" "}
				<Link
					href="/privatnost"
					className="font-medium text-[var(--primary)] hover:underline"
				>
					Politika privatnosti
				</Link>
				, a o kolačićima na stranici{" "}
				<Link href="/kolacici" className="font-medium text-[var(--primary)] hover:underline">
					Kolačići
				</Link>
				.
			</>
		),
		answerText:
			"Kalkulator ne zahtijeva registraciju i može se koristiti anonimno. Detalje o podacima koji se u pozadini obrađuju pogledajte na stranici Politika privatnosti, a o kolačićima na stranici Kolačići.",
	},
];

export default function FaqPage() {
	return (
		<div className="mx-auto max-w-3xl px-6 py-14 space-y-8">
			<header className="space-y-2">
				<h1 className="text-2xl font-bold text-[var(--text)]">
					Česta pitanja o PPMV-u i uvozu vozila
				</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Sva pitanja koja korisnici najčešće postavljaju o izračunu PPMV-a i
					korištenju kalkulatora, na jednom mjestu.
				</p>
			</header>

			<FaqList items={FAQ_ITEMS} />
			<FaqSchema items={FAQ_ITEMS} />

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Povezane stranice
				</h2>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<Link
							href="/kako-se-izracunava-ppmv"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							Kako se izračunava PPMV
						</Link>{" "}
						— puna formula i primjer izračuna.
					</li>
					<li>
						<Link href="/nedc-vs-wltp" className="font-medium text-[var(--primary)] hover:underline">
							NEDC vs. WLTP
						</Link>{" "}
						— koji CO2 podatak vrijedi za vaše vozilo.
					</li>
					<li>
						<Link
							href="/vodic-uvoz-njemacka"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							Vodič za uvoz automobila iz Njemačke
						</Link>{" "}
						— svi koraci uvoza, ne samo porez.
					</li>
					<li>
						<Link href="/o-kalkulatoru" className="font-medium text-[var(--primary)] hover:underline">
							O kalkulatoru
						</Link>{" "}
						— metodologija i izvori.
					</li>
				</ul>
			</section>

			<div className="pt-2">
				<CalculatorCta />
			</div>
		</div>
	);
}
