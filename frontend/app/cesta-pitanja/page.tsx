import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";
import { FaqList, FaqSchema, type FaqItem } from "@/components/Faq";

export const metadata: Metadata = {
	title: "Česta pitanja o PPMV-u i uvozu vozila",
	description:
		"Odgovori na pitanja o PPMV-u: tko ga plaća, u kojem roku se prijavljuje, kad se plaća PDV, gdje piše CO2 vrijednost i kako radi ovaj kalkulator.",
	alternates: { canonical: "/cesta-pitanja" },
};

const link = "font-medium text-[var(--primary)] hover:underline";

const FAQ_ITEMS: FaqItem[] = [
	{
		question: "Što je PPMV i kada se plaća?",
		answer:
			"Posebni porez na motorna vozila plaća se prije prve registracije vozila u Hrvatskoj. Iznos se dobiva zbrajanjem vrijednosne komponente, koja ovisi o cijeni vozila, i ekološke komponente, koja ovisi o emisiji CO2. Za rabljena vozila taj se zbroj umanjuje prema tablici amortizacije po starosti.",
	},
	{
		question: "Plaća li se PPMV i za vozilo kupljeno u EU?",
		answer:
			"Da. PPMV je nacionalni porez vezan uz prvu registraciju u Hrvatskoj i ne ovisi o tome odakle vozilo dolazi.",
	},
	{
		question: "Plaća li se carina i PDV pri uvozu iz EU?",
		answer:
			"Carine unutar EU nema. PDV se za rabljeno vozilo u pravilu ne plaća jer je već plaćen u državi kupnje. Iznimka je novo prijevozno sredstvo, dakle vozilo isporučeno unutar šest mjeseci od prve uporabe ili s manje od 6.000 prijeđenih kilometara. Za njega se plaća hrvatski PDV od 25%.",
	},
	{
		question: "Plaća li se PPMV i za novo i za rabljeno vozilo?",
		answer:
			"Oboje podliježe porezu. Novo vozilo plaća puni iznos, a rabljenom se iznos množi postotkom iz tablice amortizacije, koji ovisi o broju punih mjeseci od prve registracije.",
	},
	{
		question: "U kojem roku moram prijaviti PPMV?",
		answer:
			"U roku od 15 dana od dana unosa vozila u Hrvatsku, na obrascu PP-MV, carinskom uredu nadležnom prema vašem prebivalištu ili sjedištu. Prijava se može predati i elektronički kroz sustav e-Građani.",
	},
	{
		question: "Mogu li registrirati vozilo prije nego platim PPMV?",
		answer:
			"Ne. Registracija je moguća tek kad je porez plaćen i kad Carinska uprava to evidentira, pa prijava PPMV-a dolazi prije tehničkog pregleda i registracije.",
	},
	{
		question: "Je li ovo službeni izračun?",
		answer:
			"Nije. Ovo je procjena po javno dostupnim propisima, Uredbi NN 156/22 i Pravilniku o posebnom porezu na motorna vozila. Obvezujući iznos utvrđuje Carinska uprava u poreznom rješenju.",
	},
	{
		question: "Kako kalkulator dolazi do iznosa?",
		answer: (
			<>
				Zbraja vrijednosnu i ekološku komponentu iz tablica Uredbe, primjenjuje
				umanjenja za vrstu vozila i na kraju množi postotkom amortizacije. Svaki
				korak, s primjerom u brojevima, opisan je na stranici{" "}
				<Link href="/kako-se-izracunava-ppmv" className={link}>
					Kako se izračunava PPMV
				</Link>
				.
			</>
		),
		answerText:
			"Zbraja vrijednosnu i ekološku komponentu iz tablica Uredbe, primjenjuje umanjenja za vrstu vozila i na kraju množi postotkom amortizacije. Svaki korak je opisan na stranici Kako se izračunava PPMV.",
	},
	{
		question: "Koja je razlika između NEDC i WLTP vrijednosti CO2?",
		answer: (
			<>
				To su dva ciklusa mjerenja. Vozila prvi put registrirana do 31.12.2020.
				računaju se po NEDC tablicama, a ona registrirana od 1.1.2021. po WLTP
				tablicama, koje su zasebne i imaju druge granice razreda. Detaljnije na
				stranici{" "}
				<Link href="/nedc-vs-wltp" className={link}>
					NEDC ili WLTP
				</Link>
				.
			</>
		),
		answerText:
			"To su dva ciklusa mjerenja. Vozila prvi put registrirana do 31.12.2020. računaju se po NEDC tablicama, a ona registrirana od 1.1.2021. po WLTP tablicama, koje su zasebne i imaju druge granice razreda.",
	},
	{
		question: "Gdje piše CO2 vrijednost mog vozila?",
		answer:
			"U COC dokumentu pod točkom 49 i u prometnoj dozvoli u polju V.7. Oglasi tu vrijednost često navode, ali je znaju prepisati s druge izvedbe istog modela, pa je prije prijave usporedite s dokumentom.",
	},
	{
		question: "Koliko je pouzdana procjena CO2 s Wikipedije?",
		answer:
			"Dovoljno da vidite jeste li u pravom redu veličine, ali ne dovoljno da se na nju osloni porezni izračun. Zato se njome CO2 polje nikad ne popunjava automatski, nego stoji kao raspon za usporedbu s COC dokumentom.",
	},
	{
		question: "S kojih stranica kalkulator može pročitati oglas?",
		answer:
			"S mobile.de, AutoScout24, Njuškala i autobid.de. Zalijepite poveznicu i kalkulator pokušava pročitati marku, model, cijenu, CO2 i datum prve registracije.",
	},
	{
		question: "Što ako poveznica ne radi ili se podaci ne pročitaju?",
		answer:
			"Sve možete unijeti ručno. Ispod polja za poveznicu nalazi se i pretraga baze vozila, a svako pojedino polje možete popuniti ili ispraviti sami.",
	},
	{
		question: "Kalkulator nudi nekoliko vozila iz baze. Koje odabrati?",
		answer:
			"Kad podudaranje nije sigurno, prikazuje se rangirana lista umjesto automatskog odabira, jer bi kriva cijena ili CO2 pokvarili cijeli izračun. Odaberite red koji odgovara motoru, snazi i godini iz oglasa.",
	},
	{
		question: "Plaćaju li električna vozila PPMV?",
		answer: "Ne. Vozila s emisijom 0 g/km oslobođena su poreza u cijelosti.",
	},
	{
		question: "Kakvo umanjenje imaju plug-in hibridi?",
		answer:
			"Umanjenje je brojčano jednako dometu vožnje na struju u gradskoj vožnji (EAER city, u kilometrima), najviše 100%. Domet od 59 km znači umanjenje od 59%.",
	},
	{
		question: "Postoji li umanjenje za vozila s više sjedala i za kampere?",
		answer:
			"Vozilo s 8 sjedala plaća polovicu iznosa, s 9 i više sjedala četvrtinu, a kamperi 15%. Umanjenja se primjenjuju automatski kad u obrascu unesete te podatke.",
	},
	{
		question: "Je li trošak prijevoza uključen u izračun?",
		answer: (
			<>
				Nije. Kalkulator računa samo PPMV. Prijevoz, izvozne tablice,
				homologacija, tehnički pregled i registracijske pristojbe dolaze zasebno.
				Pregled svih koraka i troškova je u{" "}
				<Link href="/vodic-uvoz-njemacka" className={link}>
					vodiču za uvoz auta iz Njemačke
				</Link>
				.
			</>
		),
		answerText:
			"Nije. Kalkulator računa samo PPMV. Prijevoz, izvozne tablice, homologacija, tehnički pregled i registracijske pristojbe dolaze zasebno.",
	},
	{
		question: "Trebam li COC dokument i što ako ga vozilo nema?",
		answer:
			"COC dokument nosi službenu CO2 vrijednost i tehničke podatke potrebne za homologaciju, pa ga tražite od prodavača prije kupnje. Ako ga nema, zamjena je potvrda proizvođača koju izdaje ovlašteni zastupnik marke u Hrvatskoj, uz naknadu.",
	},
	{
		question: "Što je homologacija i tko je provodi?",
		answer:
			"To je utvrđivanje sukladnosti pojedinačnog vozila, provjera odgovara li vozilo propisima za svoju kategoriju. Provode je Centar za vozila Hrvatske i Hrvatski autoklub na ispitnim mjestima u stanicama za tehnički pregled.",
	},
	{
		question: "Je li korištenje kalkulatora besplatno?",
		answer: "Jest, i ne traži registraciju.",
	},
	{
		question: "Što je carVertical poveznica na stranici?",
		answer:
			"Partnerska (affiliate) poveznica prema carVerticalu, servisu za provjeru povijesti vozila po VIN broju. Ako kliknete i kupite provjeru, kalkulator može dobiti proviziju. Vama cijena ostaje ista.",
	},
	{
		question: "Koje podatke kalkulator prikuplja o meni?",
		answer: (
			<>
				Račun nije potreban i kalkulator se koristi anonimno. Što se ipak
				obrađuje u pozadini, primjerice hashirana IP adresa radi sprječavanja
				zlouporabe, piše u{" "}
				<Link href="/privatnost" className={link}>
					politici privatnosti
				</Link>
				, a o kolačićima na stranici{" "}
				<Link href="/kolacici" className={link}>
					Kolačići
				</Link>
				.
			</>
		),
		answerText:
			"Račun nije potreban i kalkulator se koristi anonimno. Što se ipak obrađuje u pozadini, primjerice hashirana IP adresa radi sprječavanja zlouporabe, piše u politici privatnosti, a o kolačićima na stranici Kolačići.",
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
					Porez, rokovi, papiri i rad samog kalkulatora, na jednom mjestu.
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
						<Link href="/kako-se-izracunava-ppmv" className={link}>
							Kako se izračunava PPMV
						</Link>
						: formula i primjer izračuna.
					</li>
					<li>
						<Link href="/nedc-vs-wltp" className={link}>
							NEDC ili WLTP
						</Link>
						: koja CO2 vrijednost vrijedi za vaše vozilo.
					</li>
					<li>
						<Link href="/vodic-uvoz-njemacka" className={link}>
							Vodič za uvoz auta iz Njemačke
						</Link>
						: svi koraci postupka, ne samo porez.
					</li>
					<li>
						<Link href="/o-kalkulatoru" className={link}>
							O kalkulatoru
						</Link>
						: izvori i granice alata.
					</li>
				</ul>
			</section>

			<div className="pt-2">
				<CalculatorCta />
			</div>
		</div>
	);
}
