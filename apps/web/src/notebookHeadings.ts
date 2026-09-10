import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize from 'rehype-sanitize';
import { markdownSchema } from './Markdown';

const parser = unified()
  .use(remarkParse)
  .use(remarkGfm)
  .use(remarkMath)
  .use(remarkRehype, { allowDangerousHtml: true })
  .use(rehypeRaw)
  .use(rehypeSanitize, markdownSchema);

type Node = { type: string; tagName?: string; value?: string; children?: Node[] };
const label = (node: Node): string =>
  node.type === 'text' ? node.value || '' : (node.children || []).map(label).join('');

/** Match rendered headings, including HTML and setext, without treating code as headings. */
export function notebookHeadings(source: string) {
  const headings: { title: string; level: number }[] = [];
  function visit(node: Node) {
    if (node.type === 'element' && /^h[1-6]$/.test(node.tagName || '')) {
      headings.push({
        title: label(node).trim() || 'Untitled heading',
        level: Number(node.tagName![1]),
      });
    }
    node.children?.forEach(visit);
  }
  visit(parser.runSync(parser.parse(source)));
  return headings;
}
