import ReactMarkdown, { defaultUrlTransform, type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import 'katex/dist/katex.min.css';

export const markdownSchema: typeof defaultSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [['className', /^language-./, 'math-inline', 'math-display']],
  },
  // Inline images may use data URLs; the image renderer below still refuses remote sources.
  protocols: {
    ...defaultSchema.protocols,
    src: [...(defaultSchema.protocols?.src || []), 'data'],
  },
};

const urlScheme = /^[a-z][a-z\d+.-]*:/i;

/** Whether a URL stays on this installation (relative or same-origin path) or is an inline image. */
export function isLocalResource(src: unknown): src is string {
  if (typeof src !== 'string') return false;
  // Browsers ignore tabs and newlines in URLs and treat backslashes like slashes.
  const url = src
    .replace(/[\t\n\r]/g, '')
    .trim()
    .replace(/\\/g, '/');
  if (/^data:image\//i.test(url)) return true;
  if (!url || url.startsWith('//')) return false;
  return !urlScheme.test(url);
}

/** Whether every candidate in a srcset attribute is a local resource. */
export function isLocalSrcSet(srcSet: unknown) {
  return (
    typeof srcSet === 'string' &&
    srcSet.split(',').every((candidate) => {
      const url = candidate.trim().split(/\s+/)[0];
      return !url || isLocalResource(url);
    })
  );
}

export function externalImageLabel(alt?: string | null) {
  return `External image not loaded${alt ? `: ${alt}` : ''}`;
}

/** The link target for a refused image, limited to web URLs. */
export function externalImageHref(src: unknown) {
  const url = typeof src === 'string' ? src.trim() : '';
  return /^(https?:)?\/\//i.test(url) ? url : undefined;
}

export function ExternalImageLink({ src, alt }: { src: unknown; alt?: string }) {
  const href = externalImageHref(src);
  const label = externalImageLabel(alt);
  return href ? (
    <a href={href} target="_blank" rel="noreferrer noopener" className="external-image-link">
      {label}
    </a>
  ) : (
    <span className="external-image-link">{label}</span>
  );
}

/** Render only local images so imported or user content never fetches remote resources. */
export const markdownComponents: Components = {
  img: ({ src, alt, title, width, height }) =>
    isLocalResource(src) ? (
      <img src={src} alt={alt} title={title} width={width} height={height} loading="lazy" />
    ) : (
      <ExternalImageLink src={src} alt={alt} />
    ),
  source: ({ srcSet, media, type, sizes }) =>
    isLocalSrcSet(srcSet) ? <source srcSet={srcSet} media={media} type={type} sizes={sizes} /> : null,
};

function markdownUrlTransform(url: string, key: string) {
  return key === 'src' && /^data:image\//i.test(url.trim()) ? url : defaultUrlTransform(url);
}

export default function Markdown({ children }: { children: string }) {
  return (
    <div className="notebook-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        // Parse embedded HTML, sanitize it, then generate trusted math markup.
        rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSchema], rehypeKatex]}
        components={markdownComponents}
        urlTransform={markdownUrlTransform}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
