import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";
import { FaqList, FaqSchema, type FaqItem } from "@/components/Faq";

export const metadata: Metadata = {
	title: "NEDC ili WLTP: koji CO2 vrijedi za PPMV",
	description:
		"Razlika između NEDC i WLTP mjerenja CO2, zašto je 1.1.2021. presudan datum za PPMV i gdje u dokumentima vozila pronaći točnu vrijednost.",
	alternates: { canonical: "/nedc-vs-wltp" },
};

const FAQ_ITEMS: FaqItem[] = [
	{
		question: "Vrijedi li datum proizvodnje ili datum registracije?",
		answer:
			"Datum prve registracije. Vozilo proizvedeno krajem 2020., a prvi put registrirano u 2021., računa se po WLTP tablicama.",
	},
	{
		question: "Oglas navodi dvije CO2 vrijednosti. Koju uzeti?",
		answer:
			"Onu koja odgovara ciklusu za datum prve registracije: NEDC za registraciju do 31.12.2020., WLTP za registraciju od 1.1.2021. Njemački oglasi za vozila iz 2018. do 2020. često navode obje, jer su se u tom razdoblju prijavljivale i WLTP i preračunata NEDC vrijednost.",
	},
	{
		question: "Zašto je WLTP vrijednost viša od NEDC vrijednosti za isti auto?",
		answer:
			"Zato što je test stroži, a ne zato što auto troši više. Istraživanja Zajedničkog istraživačkog centra Europske komisije i ICCT-a pokazuju omjer WLTP prema NEDC otprilike od 1,1 do 1,4, ovisno o vrsti pogona i o tome koliko je vozilo emisivno.",
	},
	{
		question: "Što ako se vrijednost iz oglasa razlikuje od one u COC dokumentu?",
		answer:
			"Mjerodavan je COC dokument. Oglasi se pišu ručno i CO2 je jedno od polja koje prodavači najčešće upišu krivo ili prepišu s druge izvedbe istog modela.",
	},
];

export default function NedcVsWltpPage() {
	return (
		<div className="mx-auto max-w-3xl px-6 py-14 space-y-10">
			<header className="space-y-2">
				<h1 className="text-2xl font-bold text-[var(--text)]">
					NEDC ili WLTP: koji CO2 vrijedi za PPMV
				</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Dva ciklusa mjerenja i dvije porezne tablice. Datum prve registracije
					određuje koja se primjenjuje.
				</p>
			</header>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Kratko: što je koji ciklus
				</h2>
				<p>
					NEDC (New European Driving Cycle) je stariji laboratorijski ciklus za
					mjerenje potrošnje i emisija. Vozio se blago, s niskim brzinama i
					umjerenim ubrzanjima, pa su izmjerene vrijednosti bile osjetno niže od
					stvarne potrošnje na cesti.
				</p>
				<p>
					WLTP (Worldwide Harmonised Light Vehicle Test Procedure) ga je
					zamijenio. Test traje dulje, uključuje veće brzine i oštrija ubrzanja i
					uzima u obzir dodatnu opremu konkretnog primjerka. Za nove tipove
					vozila obvezan je od rujna 2017., a za sva nova vozila od rujna 2018.
					U prijelaznom razdoblju do kraja 2020. proizvođači su uz WLTP
					prijavljivali i preračunatu NEDC vrijednost, zbog čega za vozila iz tog
					razdoblja često postoje dva broja.
				</p>
				<p>
					Isti auto po WLTP-u ispada emisivniji nego po NEDC-u, obično u omjeru
					od otprilike 1,1 do 1,4. Auto nije počeo trošiti više, promijenio se
					način mjerenja.
				</p>
			</section>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Zašto je 1.1.2021. presudan za PPMV
				</h2>
				<p>
					Uredba NN 156/22 propisuje dva odvojena kompleta tablica. Vozila prvi
					put registrirana do 31.12.2020. računaju se po NEDC tablicama, vozila
					registrirana od 1.1.2021. po WLTP tablicama. To nisu iste tablice s
					pomaknutim granicama, nego zasebne tablice s vlastitim razredima i
					iznosima, i za vrijednosnu i za ekološku komponentu.
				</p>
				<p>
					Praktična posljedica: unos WLTP vrijednosti za vozilo iz 2019. daje
					previsok porez, jer se veći broj gura u NEDC tablicu koja je pisana za
					manje brojeve. Obrnuto, NEDC vrijednost za vozilo iz 2022. daje
					prenizak iznos. Kalkulator sam bira tablicu prema datumu prve
					registracije koji unesete, ali CO2 morate unijeti iz ispravnog ciklusa.
				</p>
			</section>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Gdje piše CO2 vrijednost vašeg vozila
				</h2>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">COC dokument</span>{" "}
						(potvrda o sukladnosti) je najpouzdaniji izvor. CO2 se nalazi pod
						točkom 49.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Prometna dozvola
						</span>{" "}
						vozila, hrvatska i njemačka, ima CO2 u polju V.7.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">Sam oglas</span>{" "}
						često navodi CO2 u tehničkim podacima, ali ga prodavači znaju
						prepisati s druge izvedbe. Uzmite ga kao orijentaciju, a ne kao
						dokaz.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Ovaj kalkulator
						</span>{" "}
						pokušava CO2 pronaći u bazi službenih cjenika uvoznika kad ga oglas
						ne navodi. Ako ni tamo nema pogotka, ponudi orijentacijski raspon s
						Wikipedije, koji služi samo za grubu provjeru i ne ulazi u izračun.
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
					Kako te tablice ulaze u konačni iznos, s primjerom izračuna, piše na
					stranici{" "}
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
				<CalculatorCta>Unesite CO2 i datum registracije</CalculatorCta>
			</div>
		</div>
	);
}
