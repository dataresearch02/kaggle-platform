import ReactMarkdown from 'react-markdown';
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
};

export default function Markdown({ children }: { children: string }) {
  return (
    <div className="notebook-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        // Parse embedded HTML, sanitize it, then generate trusted math markup.
        rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSchema], rehypeKatex]}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
