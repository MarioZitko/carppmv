import type { Metadata } from "next";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import "./globals.css";
import { MobileNav } from "@/components/MobileNav";
import { SupportSection } from "@/components/SupportSection";

// globals.css named both faces but nothing ever loaded them, so the whole UI
// silently fell back to the system stack. latin-ext is required, not optional:
// the entire interface is Croatian (č, ć, ž, š, đ).
const inter = Inter({
	subsets: ["latin", "latin-ext"],
	variable: "--font-inter",
	display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
	subsets: ["latin", "latin-ext"],
	weight: ["400", "600"],
	variable: "--font-ibm-plex-mono",
	display: "swap",
});

const SITE_URL = "https://kalkulatoruvoza.com";
const SITE_NAME = "carPPMV";
const SITE_TITLE = "carPPMV: kalkulator PPMV-a za uvoz auta";
const DESCRIPTION =
	"Besplatan izračun posebnog poreza na motorna vozila (PPMV) pri uvozu auta u Hrvatsku. Zalijepite poveznicu oglasa s mobile.de, AutoScout24, autobid.de ili Njuškala, ili pretražite bazu vozila, i odmah vidite procjenu poreza.";

const NAV_LINKS = [
	{ href: "/", label: "Kalkulator" },
	{ href: "/kako-se-izracunava-ppmv", label: "Kako se računa" },
	{ href: "/nedc-vs-wltp", label: "NEDC ili WLTP" },
	{ href: "/vodic-uvoz-njemacka", label: "Uvoz iz Njemačke" },
	{ href: "/cesta-pitanja", label: "Pitanja" },
] as const;

const FOOTER_LINKS = [
	{ href: "/kako-se-izracunava-ppmv", label: "Kako se izračunava PPMV" },
	{ href: "/nedc-vs-wltp", label: "NEDC ili WLTP" },
	{ href: "/vodic-uvoz-njemacka", label: "Uvoz auta iz Njemačke" },
	{ href: "/cesta-pitanja", label: "Česta pitanja" },
	{ href: "/o-kalkulatoru", label: "O kalkulatoru" },
	{ href: "/privatnost", label: "Privatnost" },
	{ href: "/kolacici", label: "Kolačići" },
] as const;

export const metadata: Metadata = {
	metadataBase: new URL(SITE_URL),
	title: {
		default: SITE_TITLE,
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
		title: SITE_TITLE,
		description: DESCRIPTION,
	},
	twitter: {
		card: "summary_large_image",
		title: SITE_TITLE,
		description: DESCRIPTION,
	},
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="hr" className={`h-full ${inter.variable} ${ibmPlexMono.variable}`}>
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
					<div className="mx-auto max-w-6xl px-4 sm:px-6 py-4 flex items-center justify-between">
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
									· izračun PPMV-a
								</span>
							</span>
						</Link>
						<nav className="hidden md:flex gap-1 text-sm font-medium">
							{NAV_LINKS.map((link) => (
								<Link
									key={link.href}
									href={link.href}
									className="rounded-lg px-3 py-2 text-[var(--text)] hover:bg-[var(--primary-soft)] hover:text-[var(--primary)] transition-colors"
								>
									{link.label}
								</Link>
							))}
						</nav>
						<MobileNav links={NAV_LINKS} />
					</div>
				</header>
				<main className="flex-1">{children}</main>
				<footer className="border-t border-[var(--border)] mt-16">
					<div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 pb-24 lg:pb-6 space-y-4">
						<nav className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-[var(--text-soft)]">
							{FOOTER_LINKS.map((link) => (
								<Link
									key={link.href}
									href={link.href}
									className="hover:text-[var(--text)] transition-colors"
								>
									{link.label}
								</Link>
							))}
						</nav>
						<div className="flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-2 text-xs text-[var(--text-soft)]">
							<p>
								Iznos koji ovdje vidite je procjena. Obvezujući iznos utvrđuje
								Carinska uprava u poreznom rješenju.
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
