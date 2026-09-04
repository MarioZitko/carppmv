import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import "./globals.css";
import { SupportSection } from "@/components/SupportSection";

const SITE_URL = "https://kalkulatoruvoza.com";
const SITE_NAME = "carPPMV — Kalkulator uvoza";
const DESCRIPTION =
	"Besplatan kalkulator PPMV-a (posebni porez na motorna vozila) za uvoz automobila u Hrvatsku. Zalijepite link oglasa (mobile.de, autoscout24, autobid.de) ili pretražite bazu vozila i odmah dobijte procjenu carine i poreza.";

export const metadata: Metadata = {
	metadataBase: new URL(SITE_URL),
	title: {
		default: `${SITE_NAME} — izračun PPMV-a za uvoz auta`,
		template: `%s | ${SITE_NAME}`,
	},
	description: DESCRIPTION,
	keywords: [
		"PPMV kalkulator",
		"posebni porez na motorna vozila",
		"izračun PPMV",
		"uvoz automobila iz Njemačke",
		"carina za auto",
		"porez na uvoz vozila",
		"mobile.de uvoz",
		"autoscout24 uvoz",
	],
	applicationName: SITE_NAME,
	authors: [{ name: "Mario Žitković", url: "https://mariozitko.github.io" }],
	alternates: { canonical: "/" },
	robots: { index: true, follow: true },
	openGraph: {
		type: "website",
		locale: "hr_HR",
		url: SITE_URL,
		siteName: SITE_NAME,
		title: `${SITE_NAME} — izračun PPMV-a za uvoz auta`,
		description: DESCRIPTION,
	},
	twitter: {
		card: "summary_large_image",
		title: `${SITE_NAME} — izračun PPMV-a za uvoz auta`,
		description: DESCRIPTION,
	},
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="hr" className="h-full">
			<body className="min-h-full flex flex-col">
				<script
					type="application/ld+json"
					// Describes the calculator as a WebApplication so search results
					// can surface it as a free tool (rich snippet), not just a page.
					dangerouslySetInnerHTML={{
						__html: JSON.stringify({
							"@context": "https://schema.org",
							"@type": "WebApplication",
							name: SITE_NAME,
							url: SITE_URL,
							description: DESCRIPTION,
							applicationCategory: "FinanceApplication",
							operatingSystem: "Any",
							inLanguage: "hr",
							offers: { "@type": "Offer", price: "0", priceCurrency: "EUR" },
						}),
					}}
				/>
				<header className="sticky top-0 z-10 border-b border-[var(--border)] bg-white/80 backdrop-blur-sm">
					<div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
						<Link href="/" className="flex items-center gap-2.5 text-lg">
							<Image
								src="/logo.svg"
								alt="carPPMV logo"
								width={32}
								height={32}
								className="h-8 w-8 rounded-lg"
								priority
							/>
							<span>
								<span className="font-semibold text-[var(--text)]">
									carPPMV
								</span>
								<span className="hidden sm:inline text-[var(--text-soft)]">
									{" "}
									— izračun uvozne pristojbe
								</span>
							</span>
						</Link>
						<nav className="flex gap-1 text-sm font-medium">
							<Link
								href="/"
								className="rounded-lg px-3 py-2 text-[var(--text)] hover:bg-[var(--primary-soft)] hover:text-[var(--primary)] transition-colors"
							>
								Izračun PPMV-a
							</Link>
							<Link
								href="/profitability"
								className="rounded-lg px-3 py-2 text-[var(--text)] hover:bg-[var(--primary-soft)] hover:text-[var(--primary)] transition-colors"
							>
								Isplativost
							</Link>
						</nav>
					</div>
				</header>
				<main className="flex-1">{children}</main>
				<footer className="border-t border-[var(--border)] mt-16">
					<div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 space-y-4">
						<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-xs text-[var(--text-soft)]">
							<p className="flex flex-wrap items-center gap-x-1">
								<span>
									Ovo je procjena — uvijek provjerite konačan iznos u
									službenom carinskom rješenju.
								</span>
								<Link
									href="/privatnost"
									className="underline hover:text-[var(--text)] transition-colors"
								>
									Privatnost
								</Link>
								<span aria-hidden="true">·</span>
								<Link
									href="/kolacici"
									className="underline hover:text-[var(--text)] transition-colors"
								>
									Kolačići
								</Link>
							</p>
							<p>
								Izradio{" "}
								<a
									href="https://mariozitko.github.io"
									target="_blank"
									rel="noopener noreferrer"
									className="font-medium text-[var(--text)] hover:text-[var(--primary)] transition-colors"
								>
									Mario Žitković
								</a>
							</p>
						</div>
						<SupportSection />
					</div>
				</footer>
			</body>
		</html>
	);
}
