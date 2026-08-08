"use client";

import { useState } from "react";
import Image from "next/image";

/** carVertical affiliate CTA (Everflow-tracked, see docs/MONETIZATION_SPEC.md).
 * Self-styled banner — replaces the earlier CVAff SDK iframe integration per
 * carVertical's own request, so the discount is front and center and the
 * link doubles as their VIN/plate precheck deep-link when we have one. */
// carVertical's own brand blue (not this site's --accent teal) — scoped to
// this partner-branded card only, so it reads as their CTA, not ours.
const CV_BLUE = "#1352F1";
const CV_BLUE_SOFT = "#EAF0FE";

/** Single source of truth for the carVertical affiliate link shape — every
 * link on this card shares the base path + source_id/sub1 tracking params,
 * and only differs in whether a `uid` (precheck deep-link) or `sub3`
 * (VIN/plate) is attached. Previously duplicated between CV_CODE_LINK and
 * the inline `href` template, which could drift if the tracking params ever
 * changed in one place and not the other. */
function buildCarVerticalUrl(opts?: { uid?: number; effectiveId?: string }): string {
	const params = new URLSearchParams({ source_id: "AFF", sub1: "kalkulatoruvoza" });
	if (opts?.uid !== undefined) params.set("uid", String(opts.uid));
	if (opts?.effectiveId) params.set("sub3", opts.effectiveId);
	return `https://www.carvertical.deal/2CRT9JN/964QF6/?${params.toString()}`;
}

const CV_CODE_LINK = buildCarVerticalUrl();

export function CarVerticalCard({ vin }: { vin?: string | null }) {
	// Prefilled from the parsed listing when we have one, but always editable —
	// a user who came in via the "search the catalogue" tab or hasn't loaded a
	// listing yet still has a VIN/plate in hand and shouldn't be locked out of
	// the precheck link.
	const [manualId, setManualId] = useState(vin ?? "");
	// A listing can finish parsing after this card has already mounted (vin
	// starts undefined, then arrives once the fetch resolves) — sync the field
	// when that happens so the user doesn't have to retype what we already know.
	// Adjusted during render (React's recommended pattern for "derive state from
	// a changed prop") instead of an effect, so it doesn't trigger the
	// setState-in-effect cascading-render warning.
	const [prevVin, setPrevVin] = useState(vin);
	if (vin !== prevVin) {
		setPrevVin(vin);
		if (vin) setManualId(vin);
	}
	const effectiveId = (manualId || vin || "").trim();

	const href = buildCarVerticalUrl({ uid: 167, effectiveId: effectiveId || undefined });

	return (
		<div
			className="rounded-2xl border p-5 sm:p-6"
			style={{ borderColor: `${CV_BLUE}4d`, backgroundColor: CV_BLUE_SOFT }}
		>
			<div className="flex items-center gap-2 mb-1.5">
				<span
					className="rounded-full text-white text-xs font-bold px-2.5 py-1 mt-2"
					style={{ backgroundColor: CV_BLUE }}
				>
					-20%
				</span>
				<a
					href={CV_CODE_LINK}
					target="_blank"
					rel="noopener noreferrer nofollow sponsored"
				>
					<Image
						src="/carvertical-logo.svg"
						alt="carVertical"
						width={220}
						height={18}
						priority={false}
					/>
				</a>
			</div>
			<p className="text-sm text-[var(--text-soft)]">
				{vin
					? "Imamo VIN ovog vozila — provjerite kilometražu, štete i vlasništvo odmah."
					: "Unesite broj šasije ili registraciju i provjerite kilometražu, vlasništvo i je li vozilo bilo u nesreći prije kupnje."}
			</p>
			<p className="mt-2 text-sm text-[var(--text)]">
				Kôd za 20% popusta:{" "}
				<a
					href={CV_CODE_LINK}
					target="_blank"
					rel="noopener noreferrer nofollow sponsored"
					className="font-mono-tab font-bold text-base hover:underline"
					style={{ color: CV_BLUE }}
				>
					kalkulatoruvoza
				</a>
			</p>

			<div className="mt-4 flex flex-col sm:flex-row gap-2">
				<input
					type="text"
					value={manualId}
					onChange={(e) => setManualId(e.target.value)}
					placeholder="Broj šasije ili registracija (npr. ZG1234AB)"
					className="flex-1 rounded-xl border bg-white px-4 py-3 text-sm text-[var(--text)] placeholder:text-[var(--text-soft)] focus:outline-none"
					style={{ borderColor: `${CV_BLUE}4d` }}
				/>
				<a
					href={href}
					target="_blank"
					rel="noopener noreferrer nofollow sponsored"
					className="shrink-0 rounded-xl text-white px-6 py-3 text-sm font-semibold shadow-sm hover:opacity-90 transition-opacity text-center"
					style={{ backgroundColor: CV_BLUE }}
				>
					Provjeri povijest vozila →
				</a>
			</div>
		</div>
	);
}
