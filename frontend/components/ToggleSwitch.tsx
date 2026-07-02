"use client";

interface Props {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hint?: string;
}

export function ToggleSwitch({ checked, onChange, label, hint }: Props) {
  return (
    <label className="flex items-center justify-between gap-4 cursor-pointer select-none">
      <span>
        <span className="text-sm font-medium text-[var(--text)]">{label}</span>
        {hint && <span className="block text-xs text-[var(--text-soft)]">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
          checked ? "bg-[var(--primary)]" : "bg-[var(--border)]"
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-[22px]" : "translate-x-0.5"
          }`}
        />
      </button>
    </label>
  );
}
