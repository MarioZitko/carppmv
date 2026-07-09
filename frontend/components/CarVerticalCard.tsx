/** carVertical affiliate CTA (see docs/MONETIZATION_SPEC.md). Pre-fills the
 * VIN extracted from the scraped listing so the vehicle-history check is a
 * single click. Renders nothing when no VIN was extracted — never show a
 * broken/empty VIN link. */

const CARVERTICAL_LOCALE = process.env.NEXT_PUBLIC_CARVERTICAL_LOCALE || "hr";
const CARVERTICAL_AFFILIATE_ID = process.env.NEXT_PUBLIC_CARVERTICAL_AFFILIATE_ID || "";

function buildCarVerticalUrl(vin: string): string {
  const params = new URLSearchParams({
    vin,
    utm_source: "kalkulatoruvoza",
    utm_medium: "affiliate",
    utm_campaign: "ppmv_result",
  });
  if (CARVERTICAL_AFFILIATE_ID) {
    params.set("a_aid", CARVERTICAL_AFFILIATE_ID);
  }
  return `https://www.carvertical.com/${CARVERTICAL_LOCALE}/landing?${params.toString()}`;
}

export function CarVerticalCard({ vin }: { vin: string | null | undefined }) {
  if (!vin) return null;

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm px-5 py-4">
      <p className="text-sm font-medium text-[var(--text)]">Provjeri povijest vozila</p>
      <p className="text-xs text-[var(--text-soft)] mt-0.5 mb-3">
        Provjeri kilometražu, štete i vlasništvo na carVertical (partnerski link)
      </p>
      <a
        href={buildCarVerticalUrl(vin)}
        target="_blank"
        rel="noopener noreferrer sponsored"
        className="flex items-center justify-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
      >
        Provjeri povijest vozila →
      </a>
    </div>
  );
}
