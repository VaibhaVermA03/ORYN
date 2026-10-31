import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** Model output is untrusted. react-markdown does not render raw HTML (no rehype-raw), and links are
 *  restricted to http(s)/mailto and opened with noopener. Images are not rendered. */
function safeHref(href: string | undefined): string | undefined {
  if (!href) return undefined
  return /^(https?:|mailto:)/i.test(href) ? href : undefined
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-oryn">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children }) => {
            const safe = safeHref(href)
            return safe ? (
              <a href={safe} target="_blank" rel="noopener noreferrer nofollow">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            )
          },
          img: ({ alt }) => <span>{alt ?? ''}</span>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
