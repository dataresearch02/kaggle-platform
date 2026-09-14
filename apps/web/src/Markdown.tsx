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

type MarkdownNode = { type: string; value?: string; url?: string; children?: MarkdownNode[] };
// Matches the server's rule in community.py: @name outside words, links and code.
const MENTION = /(?<![\w@./+-])@([A-Za-z0-9_]{3,40})(?![\w@])/g;

/** Link @username text to profiles, only for usernames the server confirmed exist. */
export function linkMentions(node: MarkdownNode, known: Set<string>) {
  if (!node.children || node.type === 'link' || node.type === 'linkReference') return;
  node.children = node.children.flatMap((child) => {
    if (child.type !== 'text' || !child.value) {
      linkMentions(child, known);
      return [child];
    }
    const value = child.value;
    const parts: MarkdownNode[] = [];
    let last = 0;
    for (const match of value.matchAll(MENTION)) {
      const name = match[1].toLowerCase();
      if (!known.has(name) || match.index === undefined) continue;
      if (match.index > last) parts.push({ type: 'text', value: value.slice(last, match.index) });
      parts.push({
        type: 'link',
        url: `#profile/${name}`,
        children: [{ type: 'text', value: match[0] }],
      });
      last = match.index + match[0].length;
    }
    if (!parts.length) return [child];
    if (last < value.length) parts.push({ type: 'text', value: value.slice(last) });
    return parts;
  });
}

export default function Markdown({
  children,
  mentions = [],
}: {
  children: string;
  /** Existing usernames mentioned in the text, as returned by the API. */
  mentions?: string[];
}) {
  const known = new Set(mentions.map((name) => name.toLowerCase()));
  const mentionPlugin = () => (tree: unknown) => {
    if (known.size) linkMentions(tree as MarkdownNode, known);
  };
  return (
    <div className="notebook-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, mentionPlugin]}
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
