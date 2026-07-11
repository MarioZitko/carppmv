import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
	title: "carPPMV — izračun PPMV-a",
	description:
		"Procijenite hrvatski PPMV (posebni porez na motorna vozila) iz linka oglasa ili baze vozila.",
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="hr" className="h-full">
			<body className="min-h-full flex flex-col">
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
					<div className="mx-auto max-w-6xl px-4 sm:px-6 py-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-xs text-[var(--text-soft)]">
						<p>
							Ovo je procjena — uvijek provjerite konačan iznos u službenom
							carinskom rješenju.
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
				</footer>
			</body>
		</html>
	);
}
