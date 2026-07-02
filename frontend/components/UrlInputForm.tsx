"use client";

import { FormEvent, useState } from "react";

interface Props {
  onSubmit: (url: string) => void;
  loading: boolean;
}

export function UrlInputForm({ onSubmit, loading }: Props) {
  const [value, setValue] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    onSubmit(value);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-3">
      <input
        type="text"
        inputMode="url"
        placeholder="Zalijepite link oglasa (autoscout24, autobid.de, njuškalo…)"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="flex-1 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--text)] placeholder:text-[var(--text-soft)] focus:border-[var(--primary)] transition-colors"
        disabled={loading}
      />
      <button
        type="submit"
        disabled={loading || !value.trim()}
        className="rounded-xl bg-[var(--primary)] text-white px-6 py-3 text-sm font-semibold shadow-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--primary-dark)] transition-colors"
      >
        {loading ? "Dohvaćanje oglasa…" : "Učitaj oglas"}
      </button>
    </form>
  );
}
