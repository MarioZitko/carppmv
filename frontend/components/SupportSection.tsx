const REVOLUT_URL = "https://revolut.me/mariougdd";
const BUY_ME_COFFEE_URL = "https://buymeacoffee.com/mariozitko";
const PERSONAL_SITE_URL = "https://mariozitko.github.io/";

const linkButtonClass =
	"inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-xs font-semibold text-[var(--text)] hover:border-[var(--primary)]/40 hover:bg-[var(--primary)]/10 hover:text-[var(--primary)] transition-colors";

function ExternalLinkIcon() {
	return (
		<svg
			viewBox="0 0 24 24"
			fill="none"
			className="h-3 w-3 shrink-0"
			strokeWidth={2}
			stroke="currentColor"
			strokeLinecap="round"
			strokeLinejoin="round"
		>
			<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
			<polyline points="15 3 21 3 21 9" />
			<line x1="10" y1="14" x2="21" y2="3" />
		</svg>
	);
}

export function SupportSection() {
	return (
		<div className="space-y-3">
			<div className="rounded-lg border border-[var(--warn)]/30 bg-[var(--warn-bg)] p-5">
				<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
					<div>
						<p className="font-semibold text-sm text-[var(--text)] mb-0.5">
							Sviđa vam se alat?
						</p>
						<p className="text-xs text-[var(--text-soft)]">
							Kalkulator je besplatan i bez oglasa. Ako vam štedi vremena,
							možete me podržati.
						</p>
					</div>
					<div className="flex gap-2 shrink-0">
						<a
							href={REVOLUT_URL}
							target="_blank"
							rel="noopener noreferrer"
							className={linkButtonClass}
						>
							💳 Revolut
						</a>
						<a
							href={BUY_ME_COFFEE_URL}
							target="_blank"
							rel="noopener noreferrer"
							className={linkButtonClass}
						>
							☕ Buy Me a Coffee
						</a>
					</div>
				</div>
			</div>

			<div className="rounded-lg border border-[var(--accent)]/30 bg-[var(--accent-soft)] p-5">
				<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
					<div>
						<p className="font-semibold text-sm text-[var(--text)] mb-0.5">
							Trebate prilagođeno rješenje?
						</p>
						<p className="text-xs text-[var(--text-soft)]">
							Razvijam web aplikacije i automacije za male tvrtke i obrtnike.
							Pogledajte moje projekte ili me kontaktirajte.
						</p>
					</div>
					<a
						href={PERSONAL_SITE_URL}
						target="_blank"
						rel="noopener noreferrer"
						className={`${linkButtonClass} shrink-0`}
					>
						mariozitko.github.io
						<ExternalLinkIcon />
					</a>
				</div>
			</div>
		</div>
	);
}

/** Compact variant for a preview/download step, if one is ever added. */
export function SupportNudge() {
	return (
		<div className="rounded-lg border border-[var(--warn)]/30 bg-[var(--warn-bg)] px-5 py-3.5">
			<div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
				<p className="text-xs text-[var(--text-soft)]">
					Sviđa vam se alat? Časti me kavom!
				</p>
				<div className="flex gap-2 shrink-0">
					<a
						href={REVOLUT_URL}
						target="_blank"
						rel="noopener noreferrer"
						className={linkButtonClass}
					>
						💳 Revolut
					</a>
					<a
						href={BUY_ME_COFFEE_URL}
						target="_blank"
						rel="noopener noreferrer"
						className={linkButtonClass}
					>
						☕ Kava
					</a>
				</div>
			</div>
		</div>
	);
}
