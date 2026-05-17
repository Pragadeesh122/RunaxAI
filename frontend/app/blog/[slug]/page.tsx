import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MDXRemote } from "next-mdx-remote/rsc";
import rehypePrettyCode from "rehype-pretty-code";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import { visit } from "unist-util-visit";
import { formatDate, getAllPosts, getPost } from "@/lib/blog";
import MermaidDiagram from "@/components/visualizations/MermaidDiagram";

export const revalidate = 60;

/**
 * Custom rehype plugin to catch ```mermaid blocks before rehype-pretty-code
 * processes them. It transforms them into a <mermaid-diagram> element
 * which we then map to our React component.
 */
function rehypeMermaid() {
  return (tree: any) => {
    visit(tree, "element", (node: any) => {
      if (
        node.tagName === "pre" &&
        node.children?.length === 1 &&
        node.children[0].tagName === "code"
      ) {
        const codeNode = node.children[0];
        const className = codeNode.properties?.className || [];
        const isMermaid = Array.isArray(className)
          ? className.includes("language-mermaid")
          : className.includes("language-mermaid");

        if (isMermaid) {
          // Change the node to our custom component tag
          node.tagName = "mermaid-diagram";
          node.properties = {
            // The raw code is usually the first child's value
            code: codeNode.children[0]?.value || "",
          };
          // Clear children so it doesn't render the raw code block inside
          node.children = [];
        }
      }
    });
  };
}

const mdxComponents = {
  // Map the custom tag from our plugin to the React component
  "mermaid-diagram": (props: any) => <MermaidDiagram {...props} />,
};

export async function generateStaticParams() {
  const posts = await getAllPosts();
  return posts.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const post = await getPost(slug);
  if (!post) return {};
  return {
    title: post.title,
    description: post.description,
  };
}

export default async function BlogPostPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = await getPost(slug);
  if (!post) notFound();

  return (
    <article className="mx-auto max-w-6xl px-10 pt-16 pb-24">
      <Link
        href="/blog"
        className="mb-12 inline-flex items-center gap-1.5 text-[13px] text-zinc-500 transition-colors hover:text-zinc-300"
      >
        ← All posts
      </Link>

      <header className="mb-14">
        <div className="mb-5 flex items-center gap-3 text-[13px] text-zinc-500">
          <time dateTime={post.date} className="tabular-nums">
            {formatDate(post.date)}
          </time>
          <span className="text-zinc-700">·</span>
          <span>{post.readingMinutes} min read</span>
        </div>
        <h1
          className="text-6xl leading-[1.05] tracking-tighter text-zinc-50"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          {post.title}
        </h1>
        <p className="mt-6 max-w-3xl text-[18px] leading-relaxed text-zinc-400">
          {post.description}
        </p>
        <p className="mt-8 text-[14px] text-zinc-500">By {post.author}</p>
      </header>

      <div className="blog-prose max-w-4xl">
        <MDXRemote
          source={post.content}
          components={mdxComponents}
          options={{
            mdxOptions: {
              remarkPlugins: [remarkGfm],
              rehypePlugins: [
                rehypeMermaid,
                rehypeSlug,
                [
                  rehypePrettyCode,
                  {
                    theme: "github-dark-dimmed",
                    keepBackground: false,
                  },
                ],
              ],
            },
          }}
        />
      </div>

      {post.tags && post.tags.length > 0 ? (
        <div className="mt-16 flex flex-wrap gap-2 border-t border-white/5 pt-6">
          {post.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-white/5 px-2.5 py-1 text-[11px] text-zinc-500"
            >
              #{tag}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}
