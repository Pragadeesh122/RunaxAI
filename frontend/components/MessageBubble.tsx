"use client";

import {useEffect, useMemo, useState} from "react";
import {Streamdown} from "streamdown";
import {code} from "@streamdown/code";
import {ActionBarPrimitive} from "@assistant-ui/react";
import {Copy} from "@phosphor-icons/react/dist/ssr/Copy";
import {Check} from "@phosphor-icons/react/dist/ssr/Check";
import {CaretDown} from "@phosphor-icons/react/dist/ssr/CaretDown";
import {CaretUp} from "@phosphor-icons/react/dist/ssr/CaretUp";
import {FileText} from "@phosphor-icons/react/dist/ssr/FileText";
import {ArrowSquareOut} from "@phosphor-icons/react/dist/ssr/ArrowSquareOut";
import {SpinnerGap} from "@phosphor-icons/react/dist/ssr/SpinnerGap";
import "streamdown/styles.css";
import {getChatAttachmentUrl, getDocumentDownloadUrl} from "@/lib/api";
import type {ChatAttachment, Message, ProjectDocument, RetrievalSource} from "@/lib/types";
import ThinkingBlock from "./ThinkingBlock";
import QuizRenderer, {tryParseQuiz} from "./QuizRenderer";
import ChartRenderer, {tryParseChart} from "./ChartRenderer";
import AttachmentModal from "./AttachmentModal";

const streamdownPlugins = {code};
const streamdownThemes: ["github-light", "github-dark"] = ["github-light", "github-dark"];
const streamdownRemend = {
  links: true,
  images: true,
  bold: true,
  italic: true,
  inlineCode: true,
  katex: true,
};

// --- Copy Button for ActionBarPrimitive ---

import {forwardRef} from "react";

const CopyButton = forwardRef<HTMLButtonElement, React.ComponentPropsWithoutRef<"button">>(
  (props, ref) => {
    const isCopied = props["data-copied" as keyof typeof props];
    return (
      <button
        ref={ref}
        {...props}
        className={`flex items-center gap-1 px-1.5 py-1 rounded-md text-xs transition-all duration-150 ${
          isCopied
            ? 'text-emerald-400'
            : 'text-zinc-600 hover:text-zinc-400 hover:bg-white/5'
        }`}
      >
        {isCopied ? (
          <>
            <Check size={14} weight="bold" aria-hidden="true" />
            <span className="text-[11px]">Copied</span>
          </>
        ) : (
          <Copy size={14} aria-hidden="true" />
        )}
      </button>
    );
  }
);
CopyButton.displayName = "CopyButton";

// --- Attachment chips ---

function isImageAttachment(att: ChatAttachment): boolean {
  if (att.mimeType.startsWith("image/")) return true;
  const ext = att.filename.includes(".")
    ? att.filename.split(".").pop()!.toLowerCase()
    : "";
  return ["png", "jpg", "jpeg", "webp", "gif"].includes(ext);
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function AttachmentImageThumb({ storageKey, alt }: { storageKey: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    getChatAttachmentUrl(storageKey)
      .then((u) => {
        if (!cancelled) setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [storageKey]);
  if (!url) {
    return <div className="w-12 h-12 rounded-md bg-white/5 animate-pulse" aria-hidden="true" />;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return (
    <img
      src={url}
      alt={alt}
      className="w-12 h-12 rounded-md object-cover bg-black/30"
    />
  );
}

interface AttachmentChipsProps {
  attachments: ChatAttachment[];
  onOpen: (att: ChatAttachment) => void;
}

function AttachmentChips({ attachments, onOpen }: AttachmentChipsProps) {
  if (attachments.length === 0) return null;
  return (
    <div className="flex flex-wrap justify-end gap-2 max-w-[80%]">
      {attachments.map((att) => {
        const isImg = isImageAttachment(att);
        return (
          <button
            key={att.id}
            type="button"
            onClick={() => onOpen(att)}
            aria-label={`Open ${att.filename}`}
            className="group flex items-center gap-2 p-1 pr-2.5 rounded-xl bg-violet-600/10 border border-violet-500/15 hover:bg-violet-600/20 hover:border-violet-500/30 transition-colors"
          >
            {isImg ? (
              <AttachmentImageThumb storageKey={att.storageKey} alt={att.filename} />
            ) : (
              <span className="flex items-center justify-center w-12 h-12 rounded-md bg-white/5 text-zinc-300">
                <FileText size={20} aria-hidden="true" />
              </span>
            )}
            <span className="flex flex-col items-start min-w-0">
              <span className="text-xs font-medium text-zinc-100 max-w-[180px] truncate" title={att.filename}>
                {att.filename}
              </span>
              <span className="text-[10px] text-zinc-500">
                {formatBytes(att.fileSize)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

// --- Message Bubble ---

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
  isLast?: boolean;
  projectId?: string;
  projectDocuments?: ProjectDocument[];
}

interface SourceDisplayItem {
  key: string;
  source: RetrievalSource;
  document: ProjectDocument | null;
}

function normalizeSourceLabel(source: string): string {
  return source.trim().toLowerCase();
}

function matchDocumentForSource(
  source: RetrievalSource,
  documents: ProjectDocument[]
): ProjectDocument | null {
  const normalizedSource = normalizeSourceLabel(source.source);
  return (
    documents.find((document) => {
      const normalizedFilename = normalizeSourceLabel(document.filename);
      return (
        normalizedSource === normalizedFilename ||
        normalizedSource.startsWith(`${normalizedFilename} `) ||
        normalizedSource.startsWith(`${normalizedFilename}(`)
      );
    }) ?? null
  );
}

export default function MessageBubble({
  message,
  isStreaming,
  isLast = false,
  projectId,
  projectDocuments = [],
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [openingSourceKey, setOpeningSourceKey] = useState<string | null>(null);
  const [openAttachment, setOpenAttachment] = useState<ChatAttachment | null>(null);

  const messageAttachments = useMemo(() => {
    if (!isUser) return [];
    return message.attachments ?? message.metadata?.attachments ?? [];
  }, [isUser, message.attachments, message.metadata]);

  const isStructuredAgent =
    !isUser &&
    (message.agentName === "quiz" || message.agentName === "visualization");

  // Detect structured content regardless of agentName (handles session restore
  // where agentName is lost). The parsers validate structure so false positives
  // are extremely unlikely.
  const structuredType = useMemo(() => {
    if (isUser || isStreaming || !message.content) return null;
    if (tryParseQuiz(message.content)) return "quiz";
    if (tryParseChart(message.content)) return "chart";
    return null;
  }, [isUser, isStreaming, message.content]);

  // Use content directly — streaming smoothing is handled by assistant-ui runtime
  const displayContent = message.content;

  const normalizedContent = useMemo(
    () => structuredType ? "" : displayContent,
    [displayContent, structuredType]
  );

  const sourceItems = useMemo<SourceDisplayItem[]>(() => {
    const seen = new Set<string>();
    return message.sources.flatMap((source, index) => {
      const key = `${source.source}-${source.page ?? "na"}-${index}`;
      const dedupeKey = `${normalizeSourceLabel(source.source)}::${source.page ?? "na"}`;
      if (seen.has(dedupeKey)) return [];
      seen.add(dedupeKey);

      return [
        {
          key,
          source,
          document:
            projectDocuments.length > 0
              ? matchDocumentForSource(source, projectDocuments)
              : null,
        },
      ];
    });
  }, [message.sources, projectDocuments]);

  const handleOpenSource = async (item: SourceDisplayItem) => {
    if (!projectId || !item.document) return;
    setOpeningSourceKey(item.key);
    try {
      const url = await getDocumentDownloadUrl(projectId, item.document.id);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (error) {
      console.error("Failed to open source document:", error);
    } finally {
      setOpeningSourceKey(null);
    }
  };

  return (
    <div
      className={`group/message flex flex-col gap-1 animate-message-in ${
        isUser ? "items-end" : "items-start"
      }`}>
      {/* Thinking block — shows reasoning steps and tool calls */}
      {!isUser && message.thinkingEntries.length > 0 && (
        <ThinkingBlock
          entries={message.thinkingEntries}
          isStreaming={!!isStreaming}
          startedAt={message.thinkingStartedAt}
          duration={message.thinkingDuration}
        />
      )}

      {/* User attachments */}
      {isUser && messageAttachments.length > 0 && (
        <AttachmentChips attachments={messageAttachments} onOpen={setOpenAttachment} />
      )}

      {/* Message content */}
      {(displayContent || isStreaming) && (
        <div
          className={`
            relative text-sm leading-relaxed
            ${
              isUser
                ? "max-w-[80%] bg-violet-600/15 border border-violet-500/10 text-zinc-100 rounded-2xl rounded-br-sm px-4 py-3"
                : "w-full text-zinc-200"
            }
            ${!isUser && message.thinkingEntries.length > 0 && displayContent ? "animate-content-in" : ""}
          `}>
          {isUser ? (
            <p className='whitespace-pre-wrap wrap-break-word'>
              {message.content}
            </p>
          ) : isStructuredAgent && isStreaming ? (
            <div className='flex items-center gap-2 py-2'>
              <span className='w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse' />
              <span className='text-sm text-zinc-400'>
                Generating {message.agentName === "quiz" ? "quiz" : "visualization"}...
              </span>
            </div>
          ) : structuredType === "quiz" ? (
            <QuizRenderer content={message.content} messageId={message.dbId || message.id} savedMetadata={message.metadata} />
          ) : structuredType === "chart" ? (
            <ChartRenderer content={message.content} />
          ) : (
            <div className='chat-prose'>
              <Streamdown
                mode={isStreaming ? "streaming" : "static"}
                plugins={streamdownPlugins}
                shikiTheme={streamdownThemes}
                remend={streamdownRemend}
                caret="block"
                controls={{code: {copy: true, download: false}}}
                lineNumbers={false}>
                {normalizedContent}
              </Streamdown>
            </div>
          )}
        </div>
      )}

      {!isUser && sourceItems.length > 0 && (
        <div className="mt-1 w-full rounded-2xl border border-white/6 bg-white/[0.025]">
          <button
            type="button"
            onClick={() => setSourcesOpen((open) => !open)}
            className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left"
          >
            <div className="flex min-w-0 items-center gap-2">
              <FileText size={15} className="text-violet-300" />
              <span className="text-xs font-medium text-zinc-300">
                Sources
              </span>
              <span className="rounded-full border border-white/8 bg-white/[0.03] px-2 py-0.5 text-[10px] text-zinc-500">
                {sourceItems.length}
              </span>
              {message.sourcesCached ? (
                <span
                  title="Retrieved from semantic cache (cache hit)"
                  className="inline-flex items-center gap-1 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300"
                >
                  <span className="h-1 w-1 rounded-full bg-emerald-400" />
                  cache hit
                </span>
              ) : null}
            </div>
            {sourcesOpen ? (
              <CaretUp size={14} className="text-zinc-500" />
            ) : (
              <CaretDown size={14} className="text-zinc-500" />
            )}
          </button>

          {sourcesOpen && (
            <div className="flex flex-col gap-2 border-t border-white/6 px-3 py-3">
              {sourceItems.map((item) => {
                const isOpening = openingSourceKey === item.key;
                return (
                  <div
                    key={item.key}
                    className="flex items-start justify-between gap-3 rounded-xl border border-white/6 bg-black/10 px-3 py-2.5"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-zinc-200">
                        {item.source.source}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
                        {item.source.page ? (
                          <span>Page {item.source.page}</span>
                        ) : null}
                        <span>Score {item.source.score.toFixed(2)}</span>
                        {item.document ? (
                          <span className="text-zinc-600">Linked document</span>
                        ) : (
                          <span className="text-zinc-600">Preview unavailable</span>
                        )}
                      </div>
                    </div>

                    {projectId && item.document ? (
                      <button
                        type="button"
                        onClick={() => void handleOpenSource(item)}
                        disabled={isOpening}
                        className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1.5 text-[11px] text-zinc-300 transition-colors duration-150 hover:bg-white/[0.06] hover:text-zinc-100 disabled:cursor-wait disabled:opacity-60"
                      >
                        {isOpening ? (
                          <SpinnerGap size={12} className="animate-spin" />
                        ) : (
                          <ArrowSquareOut size={12} />
                        )}
                        <span>Open</span>
                      </button>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Action bar — copy via assistant-ui ActionBarPrimitive */}
      {!isUser && displayContent && !isStreaming && (
        <div
          className={`flex items-center gap-1 mt-1 transition-opacity duration-150 ${
            isLast ? 'opacity-100' : 'opacity-0 group-hover/message:opacity-100'
          }`}
        >
          <ActionBarPrimitive.Copy
            copiedDuration={2000}
            asChild
          >
            <CopyButton />
          </ActionBarPrimitive.Copy>
        </div>
      )}

      {/* Streaming indicator when no content yet and no thinking/tools */}
      {!isUser &&
        isStreaming &&
        !displayContent &&
        message.thinkingEntries.length === 0 && (
          <div className='flex items-center gap-1.5 py-1'>
            <span
              className='w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse'
              style={{animationDelay: "0ms"}}
              aria-hidden='true'
            />
            <span
              className='w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse'
              style={{animationDelay: "150ms"}}
              aria-hidden='true'
            />
            <span
              className='w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse'
              style={{animationDelay: "300ms"}}
              aria-hidden='true'
            />
          </div>
        )}

      <AttachmentModal
        attachment={openAttachment}
        onClose={() => setOpenAttachment(null)}
      />
    </div>
  );
}
