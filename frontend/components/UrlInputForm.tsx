"use client";

import { FormEvent, useState } from "react";
import { Turnstile } from "@marsidev/react-turnstile";

const TURNSTILE_SITE_KEY = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;

interface Props {
  onSubmit: (url: string, turnstileToken: string | null) => void;
  loading: boolean;
}

export function UrlInputForm({ onSubmit, loading }: Props) {
  const [value, setValue] = useState("");
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    onSubmit(value, turnstileToken);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="flex flex-col sm:flex-row gap-3">
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
      </div>
      {TURNSTILE_SITE_KEY && (
        <Turnstile
          siteKey={TURNSTILE_SITE_KEY}
          onSuccess={setTurnstileToken}
          onExpire={() => setTurnstileToken(null)}
          onError={() => setTurnstileToken(null)}
        />
      )}
    </form>
  );
}
