import { FileSearch, Layers, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'

const features: { icon: ReactNode; title: string; text: string }[] = [
  {
    icon: <FileSearch className="h-4 w-4" />,
    title: 'Every answer shows its source',
    text: 'Open the exact passage and page an answer came from.',
  },
  {
    icon: <ShieldCheck className="h-4 w-4" />,
    title: 'Private to each workspace',
    text: 'Documents and conversations never cross workspace boundaries.',
  },
  {
    icon: <Layers className="h-4 w-4" />,
    title: 'Search that reads, then ranks',
    text: 'Keyword and semantic search combined, then re-ranked for relevance.',
  },
]

/**
 * Desktop-only side panel for sign-in / sign-up pages.
 * The content is compacted to fit the available viewport height.
 */
export function AuthShowcase() {
  return (
    <aside
      aria-label="About ORYN"
      className="relative isolate hidden h-full min-h-0 overflow-hidden border-l border-line bg-chrome lg:flex lg:items-center lg:justify-center"
    >
      {/* Decorative background glow */}
      <div
        aria-hidden
        className="absolute inset-0 -z-10"
        style={{
          background:
            'radial-gradient(70% 55% at 88% 6%, color-mix(in srgb, var(--accent) 34%, transparent), transparent 70%), radial-gradient(60% 50% at 4% 96%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 70%)',
        }}
      />

      {/* Decorative dot grid */}
      <div
        aria-hidden
        className="absolute inset-0 -z-10 opacity-70"
        style={{
          backgroundImage: 'radial-gradient(var(--line) 1px, transparent 1px)',
          backgroundSize: '22px 22px',
          maskImage:
            'radial-gradient(ellipse at center, black 25%, transparent 75%)',
          WebkitMaskImage:
            'radial-gradient(ellipse at center, black 25%, transparent 75%)',
        }}
      />

      <div className="w-full max-w-md px-8 py-5 xl:max-w-lg xl:px-10">
        {/* Main heading moved to the top */}
        <h2 className="text-3xl font-semibold leading-tight tracking-tight xl:text-4xl">
          Ask your documents.
          <span className="block text-accent-fg">Trust the answer.</span>
        </h2>

        <p className="mt-3 text-sm leading-relaxed text-muted xl:text-[15px]">
          ORYN answers from your own files only, and shows the passage behind
          every claim so your team can check it in one click.
        </p>

        {/* Example question and cited answer */}
        <div aria-hidden className="relative mt-6">
          <div className="animate-[oryn-rise_0.7s_ease-out_both] rounded-2xl border border-line bg-surface/90 p-4 shadow-pop backdrop-blur">
            <p className="mb-3 text-[11px] font-medium uppercase tracking-wider text-muted">
              Example
            </p>

            <div className="flex justify-end">
              <p className="rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-[13px] text-on-accent">
                What is the refund window?
              </p>
            </div>

            <p className="mt-3 text-[13px] leading-relaxed">
              Refunds are available within{' '}
              <strong className="font-semibold">30 days</strong> of purchase.
              <span className="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded bg-accent-soft px-1 text-[10px] font-semibold text-accent-fg">
                1
              </span>
            </p>
          </div>

          <div className="-mt-3 ml-8 animate-[oryn-rise_0.7s_ease-out_0.25s_both] rounded-xl border border-line bg-surface p-3 shadow-pop">
            <div className="animate-[oryn-float_6s_ease-in-out_infinite]">
              <p className="flex items-center gap-1.5 text-[11px] font-medium text-accent-fg">
                <FileSearch className="h-3.5 w-3.5" />
                policy.pdf · page 4
              </p>

              <p className="mt-1.5 text-xs leading-relaxed text-muted">
                “…refunds are available within{' '}
                <mark className="rounded bg-accent-soft px-0.5 text-ink">
                  30 days of purchase
                </mark>
                . Contact support to start a refund.”
              </p>
            </div>
          </div>
        </div>

        {/* Features */}
        <ul className="mt-6 space-y-3">
          {features.map((f) => (
            <li key={f.title} className="flex items-start gap-3">
              <span
                aria-hidden
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-accent-fg shadow-card"
              >
                {f.icon}
              </span>

              <span className="min-w-0">
                <span className="block text-sm font-medium">{f.title}</span>
                <span className="block text-[13px] leading-snug text-muted">
                  {f.text}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  )
}
