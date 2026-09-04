export type FaqItem = {
	question: string;
	answer: React.ReactNode;
	/** Plain-text version of the answer for the FAQPage schema, when `answer`
	 * contains links or other JSX that can't be serialized into JSON-LD text. */
	answerText?: string;
};

/** Renders a JSON-LD FAQPage block for the given items. `answerText` (falling
 * back to `answer` when it's a plain string) becomes the schema's plain-text
 * `text` field — search engines don't execute JS or read JSX, so a link-only
 * answer needs an explicit text fallback or the rich-result eligibility is lost. */
export function FaqSchema({ items }: { items: FaqItem[] }) {
	const schema = {
		"@context": "https://schema.org",
		"@type": "FAQPage",
		mainEntity: items.map((item) => ({
			"@type": "Question",
			name: item.question,
			acceptedAnswer: {
				"@type": "Answer",
				text: item.answerText ?? (typeof item.answer === "string" ? item.answer : ""),
			},
		})),
	};
	return (
		<script
			type="application/ld+json"
			dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
		/>
	);
}

/** Accordion list of Q&As, native <details>/<summary> so it works without JS
 * and needs no client component. Pair with <FaqSchema items={items} /> once
 * per page (not per block) to avoid duplicate FAQPage schema. */
export function FaqList({ items }: { items: FaqItem[] }) {
	return (
		<div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm divide-y divide-[var(--border)]">
			{items.map((item) => (
				<details key={item.question} className="group px-5 py-4">
					<summary className="cursor-pointer list-none flex items-center justify-between gap-3 text-sm font-medium text-[var(--text)]">
						{item.question}
						<span
							aria-hidden="true"
							className="shrink-0 text-[var(--text-soft)] transition-transform group-open:rotate-45"
						>
							+
						</span>
					</summary>
					<div className="mt-2 text-sm leading-relaxed text-[var(--text-soft)]">
						{item.answer}
					</div>
				</details>
			))}
		</div>
	);
}
