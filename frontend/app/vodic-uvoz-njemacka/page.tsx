import type { Metadata } from "next";
import Link from "next/link";
import { CalculatorCta } from "@/components/CalculatorCta";

export const metadata: Metadata = {
	title: "Vodič za uvoz auta iz Njemačke",
	description:
		"Koraci uvoza auta iz Njemačke u Hrvatsku: papiri kod prodavača, PDV i PPMV, prijava na obrascu PP-MV u roku od 15 dana, homologacija, tehnički pregled i registracija.",
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
					Vodič za uvoz auta iz Njemačke
				</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Od oglasa do hrvatskih tablica: koji papiri trebaju, što se od poreza
					stvarno plaća i kojim redoslijedom ide postupak.
				</p>
			</header>

			<section className="space-y-6">
				<Step n={1} title="Pronađite oglas">
					<p>
						Najveći njemački oglasnici su mobile.de i AutoScout24. autobid.de je
						aukcijska platforma na kojoj uglavnom licitiraju registrirani trgovci
						i tehnički podaci, uključujući CO2, često nisu vidljivi bez prijave.
						Za procjenu poreza trebaju vam četiri podatka iz oglasa: cijena,
						emisija CO2, datum prve registracije i broj sjedala.
					</p>
				</Step>

				<Step n={2} title="Provjerite papire prije nego pošaljete kaparu">
					<p>
						Kod prodavača tražite dva dokumenta. Prvi je{" "}
						<span className="font-medium text-[var(--text)]">
							Zulassungsbescheinigung Teil II
						</span>{" "}
						(nekad Fahrzeugbrief), koji dokazuje vlasništvo i bez kojeg vozilo ne
						možete prevesti na sebe. Drugi je{" "}
						<span className="font-medium text-[var(--text)]">COC dokument</span>{" "}
						(potvrda o sukladnosti), koji nosi službenu CO2 vrijednost pod točkom
						49 i tehničke podatke potrebne za homologaciju.
					</p>
					<p>
						Ako COC-a nema, alternativa je potvrda proizvođača koju izdaje
						ovlašteni zastupnik marke u Hrvatskoj. Naplaćuje se i zna potrajati,
						pa je bolje to riješiti prije kupnje nego nakon nje. Kako pročitati
						CO2 vrijednost i koja se od dvije navedene odnosi na vaš auto, piše
						na stranici{" "}
						<Link
							href="/nedc-vs-wltp"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							NEDC ili WLTP
						</Link>
						.
					</p>
				</Step>

				<Step n={3} title="Izračunajte PPMV prije dogovora">
					<p>
						Posebni porez na motorna vozila zna biti najveća pojedinačna stavka
						nakon same cijene auta, osobito kod dizelaša s višim emisijama.
						Zalijepite poveznicu oglasa u{" "}
						<Link
							href="/"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							kalkulator
						</Link>{" "}
						i dobit ćete procjenu prije nego se obvežete na kupnju. Iznos ovisi o
						cijeni, CO2 emisiji i starosti vozila.
					</p>
				</Step>

				<Step n={4} title="Provjerite plaćate li PDV">
					<p>
						Unutar EU nema carine. PDV se za rabljeno vozilo iz druge članice u
						pravilu ne plaća u Hrvatskoj jer je već plaćen u državi kupnje. Iznimka
						je takozvano novo prijevozno sredstvo: vozilo isporučeno unutar šest
						mjeseci od prve uporabe ili s manje od 6.000 prijeđenih kilometara. Za
						njega se plaća hrvatski PDV od 25%, bez obzira na to što je plaćeno u
						Njemačkoj.
					</p>
					<p>
						Za auto od godinu ili dvije s malom kilometražom taj prag je stvarno
						blizu, pa prije kupnje usporedite datum prve uporabe i stanje brojila s
						oba kriterija.
					</p>
				</Step>

				<Step n={5} title="Dovezite ili prevezite vozilo">
					<p>
						Za vožnju iz Njemačke prodavač odjavljuje vozilo, a vi vadite izvozne
						tablice (Ausfuhrkennzeichen) s pripadajućim osiguranjem, koje vrijede
						od nekoliko tjedana do nekoliko mjeseci. Kratkotrajne tablice
						(Kurzzeitkennzeichen) vrijede pet dana i namijenjene su probnim
						vožnjama unutar Njemačke, pa nisu zamjena za izvozne. Druga opcija je
						transportna tvrtka, što košta više, ali otpadaju tablice, osiguranje i
						put.
					</p>
					<p>
						Prijevoz, gorivo i cestarine nisu dio PPMV izračuna. Držite ih kao
						zasebnu stavku u budžetu.
					</p>
				</Step>

				<Step n={6} title="Prijavite PPMV u roku od 15 dana">
					<p>
						Poreznu prijavu na obrascu PP-MV podnosite carinskom uredu nadležnom
						prema svom prebivalištu, u roku od 15 dana od dana unosa vozila u
						Hrvatsku. Prijavu možete predati i elektronički kroz sustav e-Građani,
						uz vjerodajnicu značajne razine sigurnosti, pa rješenje i obavijesti
						stižu u korisnički pretinac bez odlaska u carinski ured.
					</p>
					<p>
						Carinska uprava donosi rješenje s konačnim iznosom. Dok PPMV nije
						plaćen i evidentiran, vozilo se ne može registrirati.
					</p>
				</Step>

				<Step n={7} title="Homologirajte vozilo">
					<p>
						Uvezeno vozilo prolazi utvrđivanje sukladnosti pojedinačnog vozila,
						postupak kojim se provjerava odgovara li propisima za svoju kategoriju.
						Provode ga Centar za vozila Hrvatske i Hrvatski autoklub na ispitnim
						mjestima u stanicama za tehnički pregled. Uz vozilo se predaje COC
						dokument ili potvrda proizvođača s tehničkom specifikacijom. Vozila
						kupljena na njemačkom tržištu u pravilu prolaze bez prepravki, jer su
						homologirana za EU.
					</p>
				</Step>

				<Step n={8} title="Tehnički pregled i registracija">
					<p>
						Nakon homologacije slijede tehnički pregled i registracija. Na
						registraciju nosite račun ili kupoprodajni ugovor, njemačku prometnu
						dozvolu i Teil II, potvrdu o sukladnosti, dokaz o plaćenom PPMV-u i
						policu obveznog osiguranja. Tek tada dobivate hrvatsku prometnu
						dozvolu i tablice.
					</p>
				</Step>
			</section>

			<section className="space-y-3">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Greške koje se najčešće ponavljaju
				</h2>
				<ul className="list-disc pl-5 space-y-2 text-sm leading-relaxed text-[var(--text-soft)]">
					<li>
						<span className="font-medium text-[var(--text)]">
							CO2 vrijednost uzeta odoka ili sa sličnog modela.
						</span>{" "}
						Ekološka komponenta ide po razredima, pa nekoliko grama razlike može
						vozilo prebaciti u viši razred i podignuti porez za nekoliko stotina
						eura.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Kupnja bez COC dokumenta.
						</span>{" "}
						Naknadno pribavljanje potvrde proizvođača košta i traje, a bez jednog
						od ta dva dokumenta homologacija stoji.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Propušten rok od 15 dana.
						</span>{" "}
						Rok teče od unosa vozila u Hrvatsku, ne od dana kad ste odlučili
						registrirati auto.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Zaboravljen PDV na gotovo novo vozilo.
						</span>{" "}
						Auto mlađi od šest mjeseci ili s manje od 6.000 km povlači hrvatski
						PDV od 25%, što lako pojede cijelu uštedu na cijeni.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Računanje samo s PPMV-om.
						</span>{" "}
						Uz porez idu prijevoz, izvozne tablice i osiguranje, homologacija,
						tehnički pregled i registracijske pristojbe.
					</li>
				</ul>
			</section>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<p>
					Detaljan prikaz formule je na stranici{" "}
					<Link
						href="/kako-se-izracunava-ppmv"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						Kako se izračunava PPMV
					</Link>
					, a odgovori na pojedinačna pitanja na stranici{" "}
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
				<CalculatorCta>Izračunajte PPMV za oglas koji ste našli</CalculatorCta>
			</div>
		</div>
	);
}
