import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
	title: "Politika privatnosti",
	description:
		"Koje podatke kalkulatoruvoza.com prikuplja, zašto, koliko dugo ih čuva i koja prava imate po GDPR-u.",
	alternates: { canonical: "/privatnost" },
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

export default function PrivacyPolicyPage() {
	return (
		<div className="mx-auto max-w-3xl px-6 py-14 space-y-10">
			<header className="space-y-2">
				<h1 className="text-2xl font-bold text-[var(--text)]">
					Politika privatnosti
				</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Zadnja izmjena: rujan 2026. Vrijedi za kalkulatoruvoza.com.
				</p>
			</header>

			<Section title="Tko je voditelj obrade">
				<p>
					Stranicu vodi Mario Žitković kao samostalni projekt. Za pitanja o
					privatnosti i zahtjeve vezane uz vaše podatke pišite na{" "}
					<a
						href="mailto:mariozitkovic@gmail.com"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						mariozitkovic@gmail.com
					</a>
					.
				</p>
			</Section>

			<Section title="Koje podatke prikupljamo i zašto">
				<p>
					Kalkulator ne traži registraciju ni prijavu i možete ga koristiti
					anonimno. U pozadini se obrađuje samo ono što je potrebno da servis
					radi i da se spriječi zlouporaba:
				</p>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">
							IP adresa se nikad ne pohranjuje u izvornom obliku.
						</span>{" "}
						Kad zalijepite poveznicu s mobile.de, IP adresa se prije spremanja
						pretvori u jednosmjerni kriptografski otisak (SHA-256 s tajnom
						soli), iz kojeg se izvorna adresa ne može rekonstruirati. Otisak
						služi samo za ograničavanje broja dohvata oglasa preko plaćenog
						vanjskog servisa (Apify), radi zaštite od automatiziranog
						izvlačenja podataka i prekomjernog troška.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Evidencija dohvata oglasa.
						</span>{" "}
						Za svaki pokušaj dohvata mobile.de oglasa bilježimo: stranicu s
						koje je oglas, ID oglasa, je li rezultat došao iz predmemorije ili
						iz plaćenog poziva, ishod (uspjeh, neuspjeh, blokiran kao bot,
						dosegnut dnevni limit) i procijenjeni trošak poziva. Riječ je o
						tehničkoj evidenciji troška. Ne sadrži ime, e-mail ni drugi osobni
						identifikator, nego samo gore opisani otisak IP adrese.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Podaci o oglasu vozila koji unesete.
						</span>{" "}
						Kad zalijepite poveznicu oglasa, s njega se očitaju javno dostupni
						podaci o vozilu (marka, model, godina, CO2, cijena i slično) radi
						izračuna. Rezultat dohvata mobile.de oglasa sprema se do 24 sata,
						kako se isti oglas ne bi ponovno plaćeno dohvaćao ako ga u tom roku
						provjeri netko drugi. To su podaci o vozilu s javnog oglasa, ne o
						vama.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Provjera da niste automatizirani program (bot).
						</span>{" "}
						Na produkcijskoj verziji stranice dio zahtjeva za mobile.de oglase
						prolazi kroz Cloudflare Turnstile, servis koji provjerava je li
						zahtjev poslao stvaran posjetitelj. Turnstile pritom može
						postaviti vlastiti kolačić, o čemu piše na{" "}
						<Link
							href="/kolacici"
							className="font-medium text-[var(--primary)] hover:underline"
						>
							stranici o kolačićima
						</Link>
						.
					</li>
				</ul>
				<p>
					Podaci koje ručno upišete u obrazac (cijena, datum prve
					registracije, broj sjedala i slično) obrađuju se u pregledniku i na
					poslužitelju radi izračuna i ne spremaju se trajno uz vas.
				</p>
			</Section>

			<Section title="Pravna osnova obrade">
				<p>
					Hashiranje IP adrese i evidencija dohvata oglasa temelje se na
					našem legitimnom interesu (čl. 6(1)(f) GDPR-a) da spriječimo
					zlouporabu i kontroliramo trošak plaćenog vanjskog servisa za
					dohvat mobile.de oglasa. Ondje gdje se koristi Cloudflare
					Turnstile, provjera se temelji na istom legitimnom interesu —
					sprječavanju automatiziranih zahtjeva.
				</p>
			</Section>

			<Section title="Koliko dugo čuvamo podatke">
				<p>
					Predmemorija dohvaćenih mobile.de oglasa briše se nakon 24 sata.
					Evidencija dohvata s hashiranom IP adresom čuva se onoliko dugo koliko
					je potrebno za praćenje troškova i sprječavanje zlouporabe. Kako je IP
					adresa nepovratno hashirana, ti se zapisi ne mogu povezati s vama kao
					pojedincem.
				</p>
			</Section>

			<Section title="S kim dijelimo podatke">
				<p>
					Ne prodajemo niti iznajmljujemo podatke. Pojedini dijelovi servisa
					oslanjaju se na vanjske obrađivače:
				</p>
				<ul className="list-disc pl-5 space-y-2">
					<li>
						<span className="font-medium text-[var(--text)]">Apify</span> —
						dohvaća sadržaj mobile.de oglasa u naše ime kad izravan pristup
						nije moguć.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">Cloudflare</span>{" "}
						— provodi Turnstile provjeru da zahtjev nije automatiziran.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">carVertical</span>{" "}
						vodi partnerska (affiliate) poveznica na ovoj stranici. Kad je
						otvorite, nalazite se na njihovoj stranici i podliježete njihovoj
						politici privatnosti. Mi tim klikom ne dobivamo vaše osobne
						podatke, nego samo podatak da je do klika došlo.
					</li>
					<li>
						<span className="font-medium text-[var(--text)]">
							Google AdSense
						</span>{" "}
						trenutno nije aktivan. Ako ga uključimo, ova politika i stranica o
						kolačićima bit će ažurirane prije prvog prikazanog oglasa.
					</li>
				</ul>
			</Section>

			<Section title="Vaša prava">
				<p>
					Prema GDPR-u imate pravo zatražiti uvid u podatke koje o vama
					obrađujemo, njihov ispravak ili brisanje, kao i uložiti prigovor na
					obradu temeljenu na legitimnom interesu. Kako hashirana IP adresa ne
					omogućuje identifikaciju konkretne osobe, povezivanje zahtjeva s
					određenim zapisima često nije izvedivo, ali svaki zahtjev poslan na{" "}
					<a
						href="mailto:mariozitkovic@gmail.com"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						mariozitkovic@gmail.com
					</a>{" "}
					razmotrit ćemo. Imate i pravo podnijeti pritužbu Agenciji za
					zaštitu osobnih podataka (AZOP) ako smatrate da je obrada u
					suprotnosti s propisima.
				</p>
			</Section>

			<Section title="Kolačići">
				<p>
					Detalje o tome koji se kolačići koriste i zašto pogledajte na{" "}
					<Link
						href="/kolacici"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						stranici o kolačićima
					</Link>
					.
				</p>
			</Section>

			<Section title="Izmjene ove politike">
				<p>
					Ako se promijeni što prikupljamo i kako, primjerice uvođenjem AdSense
					oglasa ili analitike, ova stranica bit će ažurirana prije te promjene,
					s novim datumom izmjene na vrhu.
				</p>
			</Section>
		</div>
	);
}
