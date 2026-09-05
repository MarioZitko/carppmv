"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

interface Props {
  links: ReadonlyArray<{ href: string; label: string }>;
}

/** The below-md nav dropdown. Still a native <details>, so it opens and closes
 * without JS exactly as before — the client boundary exists only to close it
 * again. Next.js client navigation doesn't remount the header, so a tapped link
 * used to navigate while leaving the menu covering the next page; an outside tap
 * had the same problem. Both are handled here rather than by turning the whole
 * header into a client component. */
export function MobileNav({ links }: Props) {
  const ref = useRef<HTMLDetailsElement>(null);
  const pathname = usePathname();

  // Close after a navigation. Tapping the link for the *current* route doesn't
  // change `pathname`, so the onClick below covers that case too.
  useEffect(() => {
    if (ref.current) ref.current.open = false;
  }, [pathname]);

  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      const el = ref.current;
      if (el?.open && !el.contains(e.target as Node)) el.open = false;
    }
    // pointerdown, not mousedown: covers touch without relying on the browser
    // synthesising a mouse event.
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  return (
    <details className="md:hidden relative group" ref={ref}>
      <summary className="cursor-pointer list-none rounded-lg px-3 py-2 text-sm font-medium text-[var(--text)] hover:bg-[var(--primary-soft)] hover:text-[var(--primary)] transition-colors">
        Izbornik
      </summary>
      <div className="absolute right-0 mt-2 w-56 rounded-xl border border-[var(--border)] bg-white shadow-lg p-1.5 flex flex-col">
        {links.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            onClick={() => {
              if (ref.current) ref.current.open = false;
            }}
            className="rounded-lg px-3 py-2 text-sm font-medium text-[var(--text)] hover:bg-[var(--primary-soft)] hover:text-[var(--primary)] transition-colors"
          >
            {link.label}
          </Link>
        ))}
      </div>
    </details>
  );
}
