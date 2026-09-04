import Link from "next/link";

export function CalculatorCta({
	children = "Izračunajte PPMV za svoje vozilo",
}: {
	children?: React.ReactNode;
}) {
	return (
		<Link
			href="/"
			className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-[var(--primary-dark)] transition-colors"
		>
			{children}
			<span aria-hidden="true">→</span>
		</Link>
	);
}
