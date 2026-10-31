import { cn } from '@/lib/utils'

// The logo is a build-time asset: any .svg inside src/assets/brand is picked up, preferring a file
// named logo.svg (case-insensitive). import.meta.glob resolves to {} when there is none, so there is
// no broken image and no invented artwork; a plain placeholder mark is shown instead.
const found = import.meta.glob('../assets/brand/*.svg', { query: '?url', import: 'default', eager: true }) as Record<string, string>
const logoUrl = (() => {
  const entries = Object.entries(found)
  const exact = entries.find(([path]) => path.toLowerCase().endsWith('/logo.svg'))
  return (exact ?? entries[0])?.[1]
})()

export function Logo({ className, showWordmark = true }: { className?: string; showWordmark?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      {logoUrl ? (
        // .oryn-logo-img turns the (black) logo white in dark mode; see index.css.
        <img src={logoUrl} alt={showWordmark ? '' : 'ORYN'} className="oryn-logo-img h-7 w-auto shrink-0" />
      ) : (
        <span aria-hidden className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-[13px] font-bold text-on-accent">
          O
        </span>
      )}
      {showWordmark && (
        // Koltav ships a single Regular weight; font-synthesis is disabled so the browser never fakes a bold.
        <span className="font-brand text-[22px] font-normal leading-none tracking-wide [font-synthesis:none]">ORYN</span>
      )}
    </span>
  )
}