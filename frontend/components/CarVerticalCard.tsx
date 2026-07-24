"use client";

import { useEffect } from "react";

/** carVertical affiliate banner (Everflow-tracked, see docs/MONETIZATION_SPEC.md).
 * Static per-partner tracking attributes — not personalized per listing, so it
 * renders unconditionally, filling the full page width below the calculator.
 * Swaps to a narrower/taller aspect below `sm` to match mobile's viewport.
 *
 * The SDK (aff.carvertical.com/sdk.js) only scans for `[data-cvaff]` elements
 * once, on the browser's `load` event, which has usually already fired by the
 * time next/script's `afterInteractive` strategy attaches the script tag — so
 * its own auto-scan is missed. We call `window.CVAff.loadBanners()` ourselves
 * once the SDK is available; it's idempotent (skips iframes whose src already
 * matches), so this is safe to call even if the SDK's own listener also runs. */
declare global {
	interface Window {
		CVAff?: { loadBanners: () => void };
	}
}

export function CarVerticalCard() {
	useEffect(() => {
		if (window.CVAff) {
			window.CVAff.loadBanners();
			return;
		}
		const interval = setInterval(() => {
			if (window.CVAff) {
				window.CVAff.loadBanners();
				clearInterval(interval);
			}
		}, 100);
		return () => clearInterval(interval);
	}, []);

	return (
		<>
			<div
				data-cvaff
				data-platform="everflow"
				data-locale="hr"
				data-partner-id="2CRT9JN"
				data-offer-id="964QF6"
				data-uid="https://www.carvertical.deal/2CRT9JN/964QF6/?source_id=AFF&sub1=kalkulatoruvoza"
				data-chan="Website"
				data-voucher="kalkulatoruvoza"
				data-integration-type="banner"
				data-variant="drowned"
				data-background="lightblue"
				className="hidden sm:block w-full"
				style={{ height: 180 }}
			/>
			<div
				data-cvaff
				data-platform="everflow"
				data-locale="hr"
				data-partner-id="2CRT9JN"
				data-offer-id="964QF6"
				data-uid="https://www.carvertical.deal/2CRT9JN/964QF6/?source_id=AFF&sub1=kalkulatoruvoza"
				data-chan="Website"
				data-voucher="kalkulatoruvoza"
				data-integration-type="banner"
				data-variant="drowned"
				data-background="lightblue"
				className="sm:hidden w-full"
				style={{ height: 280 }}
			/>
		</>
	);
}
