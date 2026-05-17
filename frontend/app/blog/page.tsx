import Link from "next/link";
import { formatDate, getAllPosts } from "@/lib/blog";

export const revalidate = 60;

export default async function BlogIndex() {
  const posts = await getAllPosts();

  return (
    <div className="mx-auto max-w-3xl px-6 pt-16 pb-24">
      <section className="mb-16">
        <p className="mb-3 text-[12px] uppercase tracking-[0.18em] text-emerald-400/80">
          Field notes
        </p>
        <h1
          className="text-5xl leading-[1.05] tracking-tight text-zinc-50"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          Writing about agents, retrieval, and the things in between.
        </h1>
        <p className="mt-5 max-w-xl text-[15px] leading-relaxed text-zinc-400">
          Design notes, engineering decisions, and the occasional postmortem
          from building RunaxAI.
        </p>
      </section>

      {posts.length === 0 ? (
        <p className="text-[14px] text-zinc-500">No posts yet.</p>
      ) : (
        <ul className="divide-y divide-white/5 border-t border-white/5">
          {posts.map((post) => (
            <li key={post.slug}>
              <Link
                href={`/blog/${post.slug}`}
                className="group block py-8 transition-colors hover:bg-white/[0.015]"
              >
                <div className="flex items-baseline justify-between gap-6">
                  <h2
                    className="text-[22px] leading-snug tracking-tight text-zinc-100 transition-colors group-hover:text-white"
                    style={{ fontFamily: "var(--font-serif)" }}
                  >
                    {post.title}
                  </h2>
                  <time
                    dateTime={post.date}
                    className="shrink-0 text-[12px] tabular-nums text-zinc-500"
                  >
                    {formatDate(post.date)}
                  </time>
                </div>
                <p className="mt-2 text-[14.5px] leading-relaxed text-zinc-400">
                  {post.description}
                </p>
                <div className="mt-3 flex items-center gap-3 text-[12px] text-zinc-500">
                  <span>{post.readingMinutes} min read</span>
                  {post.tags && post.tags.length > 0 ? (
                    <>
                      <span className="text-zinc-700">·</span>
                      <span className="flex gap-2">
                        {post.tags.map((tag) => (
                          <span key={tag}>#{tag}</span>
                        ))}
                      </span>
                    </>
                  ) : null}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
