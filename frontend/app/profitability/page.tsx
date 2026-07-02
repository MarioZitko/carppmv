export default function ProfitabilityPage() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <h1 className="text-2xl font-bold text-[var(--text)] mb-1">Isplativost</h1>
      <p className="text-sm text-[var(--text-soft)] mb-8">
        Usporedite trošak uvoza s prodajnom vrijednosti vozila.
      </p>
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm px-5 py-6 text-sm text-[var(--text-soft)]">
        Uskoro — ova stranica koristit će isto uparivanje s bazom vozila kao i kalkulator PPMV-a, čim
        backend za isplativost bude izgrađen.
      </div>
    </div>
  );
}
