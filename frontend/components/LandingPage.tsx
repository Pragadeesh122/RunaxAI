import Link from "next/link";
import { ArrowRight } from "@phosphor-icons/react/dist/ssr/ArrowRight";
import { ArrowUpRight } from "@phosphor-icons/react/dist/ssr/ArrowUpRight";
import { Brain } from "@phosphor-icons/react/dist/ssr/Brain";
import { CheckCircle } from "@phosphor-icons/react/dist/ssr/CheckCircle";
import { Database } from "@phosphor-icons/react/dist/ssr/Database";
import { Files } from "@phosphor-icons/react/dist/ssr/Files";
import { GitBranch } from "@phosphor-icons/react/dist/ssr/GitBranch";
import { Lightning } from "@phosphor-icons/react/dist/ssr/Lightning";
import { MagnifyingGlass } from "@phosphor-icons/react/dist/ssr/MagnifyingGlass";
import { ShieldCheck } from "@phosphor-icons/react/dist/ssr/ShieldCheck";
import { TrendUp } from "@phosphor-icons/react/dist/ssr/TrendUp";
import AnimatedDemo from "@/components/landing/AnimatedDemo";
import MarqueeStrip from "@/components/landing/MarqueeStrip";
import ScrollReveal from "@/components/landing/ScrollReveal";

const bg = "#111111";
const surface = "#1a1a1d";
const surfaceAlt = "#151517";
const border = "rgba(255,255,255,0.07)";
const borderSub = "rgba(255,255,255,0.05)";
const textPri = "#f4f4f5";
const textSec = "#a1a1aa";
const textMute = "#71717a";
const accent = "#10b981";

const platformTiles = [
  {
    title: "Project workspaces",
    body: "Create a project, upload PDFs, CSVs, Word docs, Markdown, or text files, then chat against that project with source-backed answers.",
    icon: Files,
    className: "md:col-span-4 md:row-span-2",
    visual: "documents",
  },
  {
    title: "General chat",
    body: "Use document search, SQL queries, web search, and browser tasks from one conversation.",
    icon: Lightning,
    className: "md:col-span-2",
    visual: "chat",
  },
  {
    title: "Memory",
    body: "Durable facts from conversations and manual memory entries stay available across sessions.",
    icon: Brain,
    className: "md:col-span-2",
    visual: "memory",
  },
  {
    title: "Tool planner",
    body: "Calls are streamed inline, deduplicated, cached when safe, and coordinated across sequential and parallel tools.",
    icon: GitBranch,
    className: "md:col-span-3",
    visual: "planner",
  },
  {
    title: "Data access",
    body: "Ask database questions in plain English while the app keeps auth, ownership, and rate limits in the request path.",
    icon: Database,
    className: "md:col-span-3",
    visual: "database",
  },
];

const workflows = [
  {
    title: "Document intelligence",
    body: "Upload files, let the worker ingest and embed them, then ask the project assistant for cited answers.",
    meta: "PDF, CSV, DOCX, MD, TXT",
  },
  {
    title: "Operational research",
    body: "Combine live web search, browser tasks, database queries, and project evidence in one response.",
    meta: "Tools stream as they run",
  },
  {
    title: "Persistent context",
    body: "Memory captures stable facts about projects, preferences, and background so follow-up work starts with context.",
    meta: "Manual and extracted facts",
  },
  {
    title: "Production feedback",
    body: "Prometheus, Grafana, Loki, Tempo, and evaluation scripts make quality and behavior observable.",
    meta: "Metrics, traces, logs, evals",
  },
];

const stackItems = [
  "Next.js app router",
  "FastAPI SSE backend",
  "PostgreSQL ownership model",
  "Redis sessions, cache, jobs, memory",
  "MinIO document storage",
  "Pinecone vector retrieval",
  "Prometheus, Loki, Tempo, Grafana",
  "Pytest and retrieval evaluation harness",
];

function RunaxMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <rect width="64" height="64" rx="16" fill="#0A0A12" />
      <circle cx="32" cy="32" r="24" stroke={accent} strokeOpacity="0.22" strokeWidth="2" />
      <path d="M32 15L49 40H15L32 15Z" stroke="#A7F3D0" strokeOpacity="0.42" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M32 32V15M32 32L49 40M32 32L15 40" stroke="#D1FAE5" strokeOpacity="0.48" strokeWidth="2" strokeLinecap="round" />
      <circle cx="32" cy="15" r="4" fill={accent} />
      <circle cx="49" cy="40" r="4" fill={accent} />
      <circle cx="15" cy="40" r="4" fill={accent} />
      <circle cx="32" cy="32" r="7" fill={accent} fillOpacity="0.32" />
      <circle cx="32" cy="32" r="4" fill="#A7F3D0" />
      <path d="M44.5 16L46 20.5L50.5 22L46 23.5L44.5 28L43 23.5L38.5 22L43 20.5L44.5 16Z" fill="#D1FAE5" />
    </svg>
  );
}

function TileVisual({ type }: { type: string }) {
  if (type === "documents") {
    return (
      <div className="mt-9 grid grid-cols-1 sm:grid-cols-[1.2fr_0.8fr] gap-4" aria-hidden="true">
        <div className="space-y-3 rounded-2xl p-4" style={{ background: "rgba(0,0,0,0.22)", border: `1px solid ${border}` }}>
          {[
            ["Board deck.pdf", "Indexed", "82%"],
            ["Revenue exports.csv", "Ready", "47.2%"],
            ["Support notes.docx", "Processing", "18%"],
          ].map(([name, status, width]) => (
            <div key={name} className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-[11px] font-medium" style={{ color: textSec }}>{name}</span>
                <span className="text-[10px] font-mono" style={{ color: status === "Processing" ? "#86efac" : textMute }}>{status}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                <div className="h-full rounded-full" style={{ width, background: "rgba(16,185,129,0.62)" }} />
              </div>
            </div>
          ))}
        </div>
        <div className="rounded-2xl p-4" style={{ background: "rgba(255,255,255,0.03)", border: `1px solid ${border}` }}>
          <p className="mb-4 text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: textMute }}>Retrieved sources</p>
          <div className="space-y-2">
            {["p.14 customer churn", "row 218 expansion", "memo onboarding gap"].map((source, index) => (
              <div key={source} className="flex items-center gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-mono" style={{ color: accent, border: "1px solid rgba(16,185,129,0.2)" }}>
                  {index + 1}
                </span>
                <span className="truncate text-[11px]" style={{ color: textMute }}>{source}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (type === "planner") {
    return (
      <div className="mt-8 flex flex-wrap items-center gap-2" aria-hidden="true">
        {["search", "query_db", "browse", "synthesize"].map((step, index) => (
          <div key={step} className="flex items-center">
            <span className="rounded-lg px-2.5 py-1 text-[10px] font-mono" style={{ color: index === 3 ? "#86efac" : textMute, background: "rgba(255,255,255,0.04)", border: `1px solid ${border}` }}>
              {step}
            </span>
            {index < 3 && <span className="mx-1.5 h-px w-5" style={{ background: border }} />}
          </div>
        ))}
      </div>
    );
  }

  if (type === "database") {
    return (
      <div className="mt-8 rounded-2xl p-4 font-mono text-[11px] leading-6" style={{ background: "rgba(0,0,0,0.28)", border: `1px solid ${border}` }} aria-hidden="true">
        <span style={{ color: "#86efac" }}>SELECT</span> churn_rate, segment<br />
        <span style={{ color: "#86efac" }}>FROM</span> account_health<br />
        <span style={{ color: "#86efac" }}>WHERE</span> quarter = &apos;Q3&apos;
        <span className="ml-1 inline-block h-3 w-0.5 rounded-sm align-middle" style={{ background: accent, animation: "blink 1s step-end infinite" }} />
      </div>
    );
  }

  if (type === "memory") {
    return (
      <div className="mt-7 space-y-2" aria-hidden="true">
        {["Prefers concise status updates", "Uses project-scoped sources", "Needs deploy-ready evidence"].map((fact) => (
          <div key={fact} className="rounded-xl px-3 py-2 text-[11px]" style={{ color: textMute, background: "rgba(255,255,255,0.035)", border: `1px solid ${border}` }}>
            {fact}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="mt-7 flex items-center gap-2 rounded-2xl px-3 py-2" style={{ background: "rgba(0,0,0,0.24)", border: `1px solid ${border}` }} aria-hidden="true">
      <MagnifyingGlass size={13} style={{ color: accent }} />
      <span className="truncate text-[11px] font-mono" style={{ color: textMute }}>Find the revenue risk behind last week&apos;s tickets</span>
    </div>
  );
}

export default function LandingPage() {
  return (
    <div className="min-h-[100dvh] overflow-x-hidden" style={{ background: bg, color: textPri }}>
      <header
        className="sticky top-0 z-40 w-full"
        style={{
          background: "rgba(17,17,17,0.82)",
          backdropFilter: "saturate(180%) blur(20px)",
          WebkitBackdropFilter: "saturate(180%) blur(20px)",
          borderBottom: `1px solid ${borderSub}`,
        }}
        role="banner"
      >
        <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-5 md:px-10">
          <Link href="/" className="flex items-center gap-2.5" aria-label="RunaxAI home">
            <RunaxMark size={24} />
            <span className="text-[13px] font-bold tracking-tight" style={{ color: textPri }}>
              RunaxAI
            </span>
          </Link>

          <nav className="hidden items-center gap-1 md:flex" aria-label="Page navigation">
            {[
              { label: "Platform", href: "#platform-heading" },
              { label: "Workflows", href: "#workflow-heading" },
              { label: "Production", href: "#production-heading" },
              { label: "Blog", href: "/blog" },
            ].map(({ label, href }) => {
              const isExternal = href.startsWith("http");
              const isInternal = href.startsWith("/");
              
              if (isInternal) {
                return (
                  <Link key={label} href={href} className="rounded-lg px-3 py-1.5 text-[13px]" style={{ color: textMute }}>
                    {label}
                  </Link>
                );
              }
              
              return (
                <a key={label} href={href} className="rounded-lg px-3 py-1.5 text-[13px]" style={{ color: textMute }}>
                  {label}
                </a>
              );
            })}
            <a href="https://github.com/Pragadeesh122/AgenticRag" target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px]" style={{ color: textMute }}>
              GitHub
              <ArrowUpRight size={11} weight="bold" aria-hidden="true" />
            </a>
          </nav>

          <div className="flex items-center gap-2">
            <Link href="/auth/signin" className="lp-nav-signin hidden rounded-full px-3.5 py-1.5 text-[13px] sm:inline-flex">
              Sign in
            </Link>
            <Link href="/chat" className="lp-btn-primary inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-[13px] font-semibold">
              Open app
              <ArrowRight size={11} weight="bold" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden" aria-labelledby="hero-heading">
          <div
            className="pointer-events-none absolute inset-0"
            aria-hidden="true"
            style={{
              backgroundImage: "radial-gradient(rgba(255,255,255,0.07) 0.8px, transparent 0.8px)",
              backgroundSize: "24px 24px",
              maskImage: "radial-gradient(ellipse 74% 54% at 50% 24%, black 12%, transparent 72%)",
              WebkitMaskImage: "radial-gradient(ellipse 74% 54% at 50% 24%, black 12%, transparent 72%)",
            }}
          />
          <div className="pointer-events-none absolute inset-0" aria-hidden="true" style={{ background: "radial-gradient(ellipse 48% 62% at 16% 34%, rgba(16,185,129,0.065), transparent)" }} />

          <div className="relative mx-auto max-w-[1400px] px-5 pb-10 pt-20 md:px-10 md:pt-28">
            <div className="grid grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-16">
              <div className="hero-fade-2 relative z-10 pt-4 md:pt-8 lg:col-span-5">
                <div className="mb-8 flex items-center gap-2 hero-fade-1">
                  <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium" style={{ background: "rgba(16,185,129,0.1)", color: "#86efac", border: "1px solid rgba(16,185,129,0.2)" }}>
                    <span className="h-1 w-1 rounded-full" style={{ background: accent }} aria-hidden="true" />
                    Self-hostable AI workspace
                  </span>
                </div>

                <h1
                  id="hero-heading"
                  className="mb-6 hero-fade-2"
                  style={{
                    fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
                    fontSize: "clamp(2.45rem, 5vw, 4.25rem)",
                    fontWeight: 720,
                    lineHeight: 1.02,
                    letterSpacing: "-0.045em",
                    color: textPri,
                  }}
                >
                  One workspace for every question your data can answer.
                </h1>

                <p className="mb-8 max-w-[470px] text-[1.02rem] leading-relaxed hero-fade-3" style={{ color: textSec }}>
                  RunaxAI brings project documents, SQL data, live web research, browser tasks, memory, and streaming tool execution into one cited assistant experience.
                </p>

                <div className="mb-10 grid grid-cols-2 gap-x-7 gap-y-4 hero-fade-3" aria-label="Platform summary">
                  {[
                    ["5", "file types ingested"],
                    ["4", "tool families"],
                    ["3", "observability planes"],
                    ["150", "backend tests passing"],
                  ].map(([value, label]) => (
                    <div key={label} style={{ borderTop: `1px solid ${borderSub}` }} className="pt-3">
                      <p className="font-mono text-xl font-semibold tracking-tight" style={{ color: textPri }}>{value}</p>
                      <p className="mt-1 text-[11px] uppercase tracking-[0.13em]" style={{ color: textMute }}>{label}</p>
                    </div>
                  ))}
                </div>

                <div className="flex flex-col items-start gap-3 hero-fade-4 sm:flex-row">
                  <Link href="/chat" className="lp-btn-primary inline-flex items-center gap-2 rounded-full px-6 py-3 text-sm font-semibold" style={{ boxShadow: "0 1px 2px rgba(0,0,0,0.3), 0 4px 16px rgba(0,0,0,0.3)" }}>
                    Open RunaxAI
                    <ArrowRight size={14} weight="bold" aria-hidden="true" />
                  </Link>
                  <Link href="/auth/signin" className="lp-btn-ghost inline-flex items-center gap-2 rounded-full px-6 py-3 text-sm font-medium">
                    Sign in
                  </Link>
                </div>
              </div>

              <div className="relative hero-fade-right lg:col-span-7">
                <div className="pointer-events-none absolute -inset-8" aria-hidden="true" style={{ background: "radial-gradient(ellipse 80% 70% at 50% 50%, rgba(16,185,129,0.04), transparent)" }} />
                <div
                  className="relative overflow-hidden"
                  style={{
                    borderRadius: "16px",
                    border: "1px solid rgba(255,255,255,0.1)",
                    background: "#141417",
                    boxShadow: "0 32px 80px -12px rgba(0,0,0,0.6), 0 8px 24px -8px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.04) inset",
                  }}
                >
                  <div className="flex items-center gap-3 px-5 py-3" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.02)" }} aria-hidden="true">
                    <div className="flex items-center gap-1.5">
                      <div className="h-[10px] w-[10px] rounded-full" style={{ background: "#ff5f57" }} />
                      <div className="h-[10px] w-[10px] rounded-full" style={{ background: "#ffbd2e" }} />
                      <div className="h-[10px] w-[10px] rounded-full" style={{ background: "#28c840" }} />
                    </div>
                    <div className="mx-auto flex h-6 flex-1 items-center justify-center gap-2 rounded-md" style={{ background: "rgba(255,255,255,0.04)", maxWidth: "300px" }}>
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: "rgba(16,185,129,0.5)" }} />
                      <span className="font-mono text-[10px]" style={{ color: "rgba(255,255,255,0.25)" }}>runaxai.com</span>
                    </div>
                  </div>

                  <div className="flex min-h-[430px] max-h-[500px]">
                    <div className="hidden w-44 shrink-0 flex-col gap-0.5 p-3 lg:flex" style={{ borderRight: "1px solid rgba(255,255,255,0.05)", background: "rgba(0,0,0,0.2)" }} aria-hidden="true">
                      <div className="mb-2 flex items-center gap-2 px-2 py-2">
                        <RunaxMark size={18} />
                        <span className="text-[10px] font-semibold" style={{ color: "rgba(255,255,255,0.4)" }}>RunaxAI</span>
                      </div>
                      <div className="mb-3 flex items-center gap-2 rounded-lg px-2.5 py-1.5" style={{ background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.15)" }}>
                        <span className="text-[10px] font-medium" style={{ color: "rgba(16,185,129,0.8)" }}>+ New workspace</span>
                      </div>
                      {[
                        { label: "Q3 risk review", active: true },
                        { label: "Project documents" },
                        { label: "Memory facts" },
                        { label: "Source exports" },
                      ].map(({ label, active }) => (
                        <div key={label} className="flex items-center rounded-md px-2.5 py-1.5" style={{ background: active ? "rgba(255,255,255,0.05)" : "transparent", borderLeft: active ? "2px solid rgba(16,185,129,0.5)" : "2px solid transparent" }}>
                          <span className="truncate text-[10px]" style={{ color: active ? "rgba(255,255,255,0.7)" : "rgba(255,255,255,0.25)" }}>{label}</span>
                        </div>
                      ))}
                    </div>

                    <div className="flex min-w-0 flex-1 flex-col">
                      <AnimatedDemo />
                    </div>
                  </div>
                </div>
                <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-16" aria-hidden="true" style={{ background: `linear-gradient(to bottom, transparent, ${bg})` }} />
              </div>
            </div>
          </div>
        </section>

        <MarqueeStrip />

        <section className="relative mx-auto max-w-[1400px] px-5 pb-20 pt-24 md:px-10" aria-labelledby="platform-heading">
          <ScrollReveal>
            <div className="mb-5 flex items-center gap-3">
              <p className="shrink-0 text-xs font-semibold uppercase tracking-[0.18em]" style={{ color: accent }}>Platform</p>
              <span className="h-px flex-1" style={{ background: borderSub }} aria-hidden="true" />
            </div>
            <h2 id="platform-heading" className="mb-5 max-w-[720px]" style={{ fontFamily: "var(--font-geist-sans), system-ui, sans-serif", fontWeight: 700, fontSize: "clamp(1.8rem, 3.8vw, 2.85rem)", letterSpacing: "-0.04em", color: textPri, lineHeight: 1.08 }}>
              The homepage now needs to describe the full application, not just a chat box.
            </h2>
            <p className="mb-14 max-w-[620px] text-[0.98rem] leading-relaxed" style={{ color: textSec }}>
              RunaxAI is a product surface for knowledge work: projects, documents, tools, memories, sessions, auth, deployment, monitoring, and evaluation are all part of the current system.
            </p>
          </ScrollReveal>

          <ScrollReveal delay={100}>
            <div className="grid grid-cols-1 gap-px overflow-hidden rounded-2xl md:grid-cols-6" style={{ background: border, border: `1px solid ${border}` }}>
              {platformTiles.map(({ title, body, icon: Icon, className, visual }) => (
                <article key={title} className={`group relative overflow-hidden p-6 md:p-8 ${className}`} style={{ background: surface }}>
                  <div className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100" aria-hidden="true" style={{ background: "radial-gradient(ellipse 64% 64% at 70% 0%, rgba(16,185,129,0.055), transparent)" }} />
                  <div className="relative">
                    <div className="mb-6 flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: "rgba(16,185,129,0.09)", border: "1px solid rgba(16,185,129,0.18)" }} aria-hidden="true">
                      <Icon size={18} weight="duotone" style={{ color: accent }} />
                    </div>
                    <h3 className="mb-3 text-base font-semibold tracking-tight" style={{ color: textPri }}>{title}</h3>
                    <p className="max-w-[540px] text-[0.93rem] leading-relaxed" style={{ color: textSec }}>{body}</p>
                    <TileVisual type={visual} />
                  </div>
                </article>
              ))}
            </div>
          </ScrollReveal>
        </section>

        <section className="relative mx-auto max-w-[1400px] px-5 pb-24 pt-12 md:px-10" aria-labelledby="workflow-heading">
          <div className="grid grid-cols-1 gap-10 lg:grid-cols-12 lg:gap-20">
            <ScrollReveal className="lg:col-span-4">
              <div className="mb-5 flex items-center gap-3">
                <p className="shrink-0 text-xs font-semibold uppercase tracking-[0.18em]" style={{ color: accent }}>Workflows</p>
                <span className="h-px flex-1" style={{ background: borderSub }} aria-hidden="true" />
              </div>
              <h2 id="workflow-heading" style={{ fontFamily: "var(--font-geist-sans), system-ui, sans-serif", fontWeight: 700, fontSize: "clamp(1.75rem, 3.5vw, 2.5rem)", letterSpacing: "-0.035em", color: textPri, lineHeight: 1.1 }}>
                Built for repeat work, not demo prompts.
              </h2>
              <p className="mt-5 max-w-[300px] text-[0.94rem] leading-relaxed" style={{ color: textSec }}>
                The app has real paths for ingestion, search, streaming response state, memory management, protected sessions, and source inspection.
              </p>
            </ScrollReveal>

            <div className="lg:col-span-8">
              {workflows.map(({ title, body, meta }, index) => (
                <ScrollReveal key={title} delay={index * 90}>
                  <div className="grid grid-cols-1 gap-4 py-7 md:grid-cols-[180px_1fr]" style={{ borderBottom: index < workflows.length - 1 ? `1px solid ${borderSub}` : "none" }}>
                    <div className="font-mono text-[11px] uppercase tracking-[0.14em]" style={{ color: textMute }}>{meta}</div>
                    <div>
                      <h3 className="mb-2 text-base font-semibold tracking-tight" style={{ color: textPri }}>{title}</h3>
                      <p className="text-[0.94rem] leading-relaxed" style={{ color: textSec }}>{body}</p>
                    </div>
                  </div>
                </ScrollReveal>
              ))}
            </div>
          </div>
        </section>

        <section className="relative w-full overflow-hidden" style={{ background: surfaceAlt, borderTop: `1px solid ${borderSub}`, borderBottom: `1px solid ${borderSub}` }} aria-labelledby="production-heading">
          <div className="pointer-events-none absolute inset-0" aria-hidden="true" style={{ backgroundImage: "radial-gradient(rgba(255,255,255,0.035) 0.8px, transparent 0.8px)", backgroundSize: "24px 24px" }} />
          <div className="relative mx-auto grid max-w-[1400px] grid-cols-1 gap-10 px-5 py-24 md:px-10 lg:grid-cols-12 lg:gap-16">
            <ScrollReveal className="lg:col-span-5">
              <div className="mb-5 flex items-center gap-3">
                <p className="shrink-0 text-xs font-semibold uppercase tracking-[0.18em]" style={{ color: accent }}>Production</p>
                <span className="h-px flex-1" style={{ background: borderSub }} aria-hidden="true" />
              </div>
              <h2 id="production-heading" className="mb-5" style={{ fontFamily: "var(--font-geist-sans), system-ui, sans-serif", fontWeight: 700, fontSize: "clamp(1.75rem, 3.5vw, 2.65rem)", letterSpacing: "-0.04em", color: textPri, lineHeight: 1.08 }}>
                The boring pieces are already part of the product.
              </h2>
              <p className="max-w-[500px] text-[0.96rem] leading-relaxed" style={{ color: textSec }}>
                RunaxAI includes the operational layers that make an AI workspace maintainable: ownership checks, secure auth cookies, background ingestion, metrics, logs, traces, and evaluation scripts.
              </p>
            </ScrollReveal>

            <ScrollReveal delay={120} className="lg:col-span-7">
              <div className="grid grid-cols-1 gap-px overflow-hidden rounded-2xl sm:grid-cols-2" style={{ background: border, border: `1px solid ${border}` }}>
                <div className="p-6" style={{ background: bg }}>
                  <div className="mb-5 flex items-center gap-3">
                    <ShieldCheck size={18} weight="duotone" style={{ color: accent }} />
                    <h3 className="text-sm font-semibold tracking-tight" style={{ color: textPri }}>Application controls</h3>
                  </div>
                  <div className="space-y-3">
                    {["Email/password and Google OAuth", "HTTP-only JWT cookies", "Protected chat and project routes", "Rate limiting with auth-aware subjects"].map((item) => (
                      <div key={item} className="flex items-start gap-2">
                        <CheckCircle size={14} weight="fill" className="mt-0.5 shrink-0" style={{ color: accent }} />
                        <span className="text-[12px] leading-relaxed" style={{ color: textSec }}>{item}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="p-6" style={{ background: bg }}>
                  <div className="mb-5 flex items-center gap-3">
                    <TrendUp size={18} weight="duotone" style={{ color: accent }} />
                    <h3 className="text-sm font-semibold tracking-tight" style={{ color: textPri }}>Runtime stack</h3>
                  </div>
                  <div className="grid grid-cols-1 gap-2">
                    {stackItems.map((item) => (
                      <div key={item} className="rounded-lg px-3 py-2 text-[11px]" style={{ color: textMute, background: "rgba(255,255,255,0.035)", border: `1px solid ${borderSub}` }}>
                        {item}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </ScrollReveal>
          </div>
        </section>

        <section className="relative w-full overflow-hidden" aria-labelledby="cta-heading" style={{ background: "#0d0d0d" }}>
          <div className="pointer-events-none absolute inset-0" aria-hidden="true" style={{ background: "radial-gradient(ellipse 55% 65% at 18% 50%, rgba(16,185,129,0.08), transparent)" }} />
          <div className="relative mx-auto grid max-w-[1400px] grid-cols-1 items-start gap-12 px-5 py-24 md:px-10 lg:grid-cols-2 lg:gap-20">
            <ScrollReveal>
              <p className="mb-7 text-xs font-semibold uppercase tracking-[0.18em]" style={{ color: accent }}>Ready when you are</p>
              <h2 id="cta-heading" className="mb-8" style={{ fontFamily: "var(--font-geist-sans), system-ui, sans-serif", fontWeight: 700, fontSize: "clamp(1.875rem, 4.5vw, 3rem)", letterSpacing: "-0.04em", color: textPri, lineHeight: 1.08 }}>
                Start with a chat. Grow into a workspace.
              </h2>
              <div className="flex flex-wrap items-center gap-5">
                <Link href="/chat" className="lp-btn-cta inline-flex items-center gap-2 rounded-full px-8 py-3.5 text-sm font-semibold">
                  Open RunaxAI
                  <ArrowUpRight size={14} weight="bold" aria-hidden="true" />
                </Link>
                <p className="text-xs" style={{ color: "rgba(255,255,255,0.24)" }}>Self-host locally or deploy with the included stack</p>
              </div>
            </ScrollReveal>

            <ScrollReveal delay={120} className="lg:pt-12">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {[
                  { label: "Upload and ask", detail: "Project files become cited answers." },
                  { label: "Research live", detail: "Web and browser tools fill the gaps." },
                  { label: "Remember context", detail: "Durable facts stay available." },
                  { label: "Measure behavior", detail: "Dashboards and evals expose quality." },
                ].map(({ label, detail }) => (
                  <div key={label} className="flex items-start gap-3">
                    <CheckCircle size={18} weight="fill" className="mt-0.5 shrink-0" style={{ color: accent }} />
                    <div>
                      <p className="text-sm font-medium" style={{ color: "rgba(255,255,255,0.82)" }}>{label}</p>
                      <p className="mt-0.5 text-xs" style={{ color: "rgba(255,255,255,0.32)" }}>{detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollReveal>
          </div>
        </section>
      </main>

      <footer className="w-full px-5 py-7 md:px-10" style={{ background: "#0d0d0d", borderTop: `1px solid ${borderSub}` }} role="contentinfo">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <RunaxMark size={18} />
            <span className="text-xs font-semibold" style={{ color: "rgba(255,255,255,0.35)" }}>RunaxAI</span>
          </div>
          <p className="text-xs" style={{ color: "rgba(255,255,255,0.18)" }}>
            Tool-augmented answers for documents, data, web research, and memory.
          </p>
        </div>
      </footer>
    </div>
  );
}
