"use client";

import Link from "next/link";

interface AuthSupportLayoutProps {
  eyebrow: string;
  title: string;
  description: string;
  sideTitle: string;
  sideDescription: string;
  sidePoints: string[];
  children: React.ReactNode;
  backHref?: string;
  backLabel?: string;
}

export default function AuthSupportLayout({
  eyebrow,
  title,
  description,
  sideTitle,
  sideDescription,
  sidePoints,
  children,
  backHref = "/auth/signin",
  backLabel = "Back to sign in",
}: AuthSupportLayoutProps) {
  return (
    <div className="relative min-h-[100dvh] overflow-hidden bg-zinc-950 text-zinc-100">
      <div className="relative z-10 mx-auto flex min-h-[100dvh] w-full max-w-6xl items-center px-6 py-10">
        <div className="hidden flex-1 pr-12 lg:block">
          <p className="mb-3 text-xs uppercase tracking-[0.24em] text-emerald-400/70">
            RunaxAI
          </p>
          <h1 className="max-w-xl text-4xl font-semibold leading-tight tracking-tight text-zinc-100">
            {sideTitle}
          </h1>
          <p className="mt-5 max-w-lg text-base leading-relaxed text-zinc-400">
            {sideDescription}
          </p>
          <div className="mt-8 space-y-3">
            {sidePoints.map((point) => (
              <div key={point} className="flex items-center gap-3 text-sm text-zinc-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400/80" />
                <span>{point}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Liquid glass refraction: 1px inner highlight + tinted diffusion shadow (skill §4) */}
        <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#151517]/95 p-7 backdrop-blur shadow-[inset_0_1px_0_rgba(255,255,255,0.06),0_24px_60px_-20px_rgba(0,0,0,0.6)]">
          <Link
            href={backHref}
            className="inline-flex text-xs uppercase tracking-[0.22em] text-zinc-500 transition-colors hover:text-zinc-300"
          >
            {backLabel}
          </Link>
          <h2 className="mt-4 text-2xl font-semibold tracking-tight text-zinc-100">{title}</h2>
          <p className="mt-1 text-sm text-zinc-400">{description}</p>
          <p className="mt-6 text-xs uppercase tracking-[0.24em] text-emerald-400/70">
            {eyebrow}
          </p>
          <div className="mt-4">{children}</div>
        </div>
      </div>
    </div>
  );
}
