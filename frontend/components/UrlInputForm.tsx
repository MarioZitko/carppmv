"use client";

import { FormEvent, useRef, useState } from "react";
import { Turnstile, TurnstileInstance } from "@marsidev/react-turnstile";

const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;

interface Props {
	onSubmit: (url: string, turnstileToken: string | null) => void;
	loading: boolean;
}

type PasteState = "idle" | "pasted" | "failed";

export function UrlInputForm({ onSubmit, loading }: Props) {
	const [value, setValue] = useState("");
	const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
	const [pasteState, setPasteState] = useState<PasteState>("idle");
	const turnstileRef = useRef<TurnstileInstance>(undefined);

	// A Turnstile token is single-use — the backend consumes it on the first
	// verify call, so resubmitting the same token on a second paste/submit
	// always 403s ("sigurnosna provjera nije uspjela"). Reset the widget right
	// after every submit so it silently mints a fresh token in the background,
	// ready before the user's next paste.
	function submitAndResetTurnstile(url: string, token: string | null) {
		onSubmit(url, token);
		setTurnstileToken(null);
		turnstileRef.current?.reset();
	}
	// Only genuinely unsupported (old browser, insecure context) hides the
	// button permanently — a denied/failed read leaves it in place so the user
	// can just tap it again, instead of the control vanishing on them.
	const [clipboardSupported] = useState(
		() => typeof navigator !== "undefined" && !!navigator.clipboard?.readText,
	);

	function handleSubmit(e: FormEvent) {
		e.preventDefault();
		if (!value.trim()) return;
		submitAndResetTurnstile(value, turnstileToken);
	}

	async function handlePaste() {
		try {
			const text = await navigator.clipboard.readText();
			const trimmed = text.trim();
			if (trimmed) {
				setValue(trimmed);
				setPasteState("pasted");
				setTimeout(() => setPasteState("idle"), 1200);
				// Pasting a link is the whole intent of this button, so skip the extra
				// tap on "Učitaj oglas" and submit right away — but only for something
				// that actually looks like a URL, so a pasted non-link doesn't fire a
				// pointless request.
				if (/^https?:\/\/\S+/i.test(trimmed)) {
					submitAndResetTurnstile(trimmed, turnstileToken);
				}
			}
		} catch {
			// Clipboard access denied for this tap (permission prompt dismissed, no
			// gesture, etc.) — surface it briefly and let the user try again.
			setPasteState("failed");
			setTimeout(() => setPasteState("idle"), 2000);
		}
	}

	return (
		<form onSubmit={handleSubmit} className="flex flex-col gap-3">
			<div className="flex flex-col sm:flex-row gap-3">
				<div className="relative flex-1">
					<input
						type="text"
						inputMode="url"
						placeholder="Zalijepite link oglasa (autoscout24, autobid.de, mobile.de)"
						value={value}
						onChange={(e) => setValue(e.target.value)}
						className={`w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] pl-4 py-3 text-sm text-[var(--text)] placeholder:text-[var(--text-soft)] focus:border-[var(--primary)] transition-colors ${
							clipboardSupported ? "pr-[5.5rem]" : "pr-4"
						}`}
						disabled={loading}
					/>
					{clipboardSupported && (
						<button
							type="button"
							onClick={handlePaste}
							disabled={loading}
							aria-label="Zalijepi iz međuspremnika"
							title="Zalijepi iz međuspremnika"
							className={`absolute right-1.5 top-1.5 bottom-1.5 flex items-center gap-1.5 rounded-lg border px-3 text-xs font-semibold transition-all active:scale-95 disabled:opacity-40 disabled:active:scale-100 ${
								pasteState === "pasted"
									? "border-[var(--primary)]/40 bg-[var(--primary)]/10 text-[var(--primary)]"
									: pasteState === "failed"
										? "border-[var(--err)]/40 bg-[var(--err-bg)] text-[var(--err)]"
										: "border-[var(--border)] bg-[var(--surface-alt)] text-[var(--text-soft)] hover:border-[var(--primary)]/40 hover:bg-[var(--primary)]/10 hover:text-[var(--primary)]"
							}`}
						>
							{pasteState === "pasted" ? (
								<>
									<svg
										viewBox="0 0 24 24"
										fill="none"
										className="h-4 w-4 shrink-0"
										strokeWidth={2.5}
										stroke="currentColor"
										strokeLinecap="round"
										strokeLinejoin="round"
									>
										<polyline points="20 6 9 17 4 12" />
									</svg>
									<span className="hidden xs:inline">Zalijepljeno</span>
								</>
							) : pasteState === "failed" ? (
								<span>Pokušaj opet</span>
							) : (
								<>
									<svg
										viewBox="0 0 24 24"
										fill="none"
										className="h-4 w-4 shrink-0"
										strokeWidth={2}
										stroke="currentColor"
										strokeLinecap="round"
										strokeLinejoin="round"
									>
										<rect x="8" y="2" width="8" height="4" rx="1" />
										<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
									</svg>
									<span>Zalijepi</span>
								</>
							)}
						</button>
					)}
				</div>
				<button
					type="submit"
					disabled={loading || !value.trim()}
					className="rounded-xl bg-[var(--primary)] text-white px-6 py-3 text-sm font-semibold shadow-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--primary-dark)] transition-colors"
				>
					{loading ? "Dohvaćanje oglasa…" : "Učitaj oglas"}
				</button>
			</div>
			{TURNSTILE_SITE_KEY && (
				<Turnstile
					ref={turnstileRef}
					siteKey={TURNSTILE_SITE_KEY}
					onSuccess={setTurnstileToken}
					onExpire={() => setTurnstileToken(null)}
					onError={() => setTurnstileToken(null)}
				/>
			)}
		</form>
	);
}
