import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
	title: "Kolačići",
	description:
		"Koje kolačiće kalkulatoruvoza.com koristi, tko ih postavlja i zašto.",
	alternates: { canonical: "/kolacici" },
};

function Row({
	name,
	who,
	purpose,
	duration,
}: {
	name: string;
	who: string;
	purpose: string;
	duration: string;
}) {
	return (
		<div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_2fr_1fr] gap-x-4 gap-y-1 py-3 border-b border-[var(--border)] last:border-b-0 text-sm">
			<span className="font-medium text-[var(--text)]">{name}</span>
			<span className="text-[var(--text-soft)]">{who}</span>
			<span className="text-[var(--text-soft)]">{purpose}</span>
			<span className="text-[var(--text-soft)]">{duration}</span>
		</div>
	);
}

export default function CookiePolicyPage() {
	return (
		<div className="mx-auto max-w-3xl px-6 py-14 space-y-8">
			<header className="space-y-2">
				<h1 className="text-2xl font-bold text-[var(--text)]">Kolačići</h1>
				<p className="text-sm text-[var(--text-soft)]">
					Zadnja izmjena: rujan 2026. Vrijedi za kalkulatoruvoza.com.
				</p>
			</header>

			<div className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<p>
					Kalkulator radi bez korisničkog računa i bez vlastite analitike, pa
					sami ne postavljamo nijedan kolačić. Jedini koji se može pojaviti
					dolazi od Cloudflare Turnstilea, vanjske usluge koja provjerava da
					zahtjev nije automatiziran, i aktivan je samo na produkcijskoj
					verziji stranice.
				</p>
				<p>
					Ako uvedemo Google AdSense ili alat za analitiku posjeta, ova tablica
					bit će ažurirana prije nego ti kolačići počnu raditi, zajedno s
					obavijesti o privoli ondje gdje je zakonski potrebna.
				</p>
			</div>

			<section className="space-y-2">
				<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm overflow-hidden">
					<div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_2fr_1fr] gap-x-4 px-5 py-3 bg-[var(--surface-alt)] text-xs font-semibold uppercase tracking-wide text-[var(--text-soft)]">
						<span>Kolačić</span>
						<span>Tko postavlja</span>
						<span>Svrha</span>
						<span>Trajanje</span>
					</div>
					<div className="px-5">
						<Row
							name="cf_clearance / __cf_bm"
							who="Cloudflare (Turnstile)"
							purpose="Nužan kolačić. Potvrđuje da zahtjev za dohvat mobile.de oglasa nije poslao automatizirani program."
							duration="Do 30 min / do 1 dan"
						/>
						<Row
							name="Affiliate praćenje (carVertical)"
							who="carVertical / Everflow"
							purpose="Postavlja se tek kad otvorite partnersku poveznicu prema carVerticalu i napustite ovu stranicu. Služi da carVertical zna da je posjet došao od nas."
							duration="Ovisi o carVertical politici"
						/>
						<Row
							name="Analitika"
							who="—"
							purpose="Trenutno se ne koristi. Ako je uvedemo, ovdje ćemo navesti alat i svrhu."
							duration="—"
						/>
						<Row
							name="Google AdSense"
							who="—"
							purpose="Trenutno nije aktivan. Kad postane, ovdje će biti popisani kolačići koje postavlja, a privola zatražena prije prikaza oglasa."
							duration="—"
						/>
					</div>
				</div>
			</section>

			<section className="space-y-3 text-sm leading-relaxed text-[var(--text-soft)]">
				<h2 className="text-lg font-semibold text-[var(--text)]">
					Kako upravljati kolačićima
				</h2>
				<p>
					Kolačiće možete obrisati ili blokirati u postavkama preglednika.
					Blokiranje Turnstile kolačića onemogućuje dohvat mobile.de oglasa,
					jer provjera tada ne može proći.
				</p>
				<p>
					Koji se drugi podaci obrađuju i zašto piše u{" "}
					<Link
						href="/privatnost"
						className="font-medium text-[var(--primary)] hover:underline"
					>
						politici privatnosti
					</Link>
					.
				</p>
			</section>
		</div>
	);
}
