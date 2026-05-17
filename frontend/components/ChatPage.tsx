"use client";

import {useState, useCallback, useEffect, useMemo, useRef} from "react";
import { signOut } from "@/lib/api";
import {CaretLeft} from "@phosphor-icons/react/dist/ssr/CaretLeft";
import {CaretRight} from "@phosphor-icons/react/dist/ssr/CaretRight";
import {PencilSimpleLineIcon} from "@phosphor-icons/react/dist/ssr/PencilSimpleLine";
import {Brain} from "@phosphor-icons/react/dist/ssr/Brain";
import {DownloadSimple} from "@phosphor-icons/react/dist/ssr/DownloadSimple";
import {useExternalStoreRuntime, AssistantRuntimeProvider} from "@assistant-ui/react";
import Sidebar from "@/components/Sidebar";
import ChatArea from "@/components/ChatArea";
import MemoryPanel from "@/components/MemoryPanel";
import {
  backendSessionExists,
  createBackendSession,
  deleteBackendSession,
  restoreBackendSession,
  streamChat,
  createChatSession,
  downloadChatSessionMarkdown,
  updateChatSession,
  deleteChatSession,
  fetchSessions,
  fetchMessages,
  saveMessages,
} from "@/lib/api";
import {convertMessage} from "@/lib/chatRuntime";
import {
  appendReasoningPart,
  appendSourceParts,
  appendTextPart,
  appendToolCallPart,
  buildAssistantPartsFromLegacy,
  getDefaultAssistantStatus,
  markRunningToolParts,
} from "@/lib/messageParts";
import type {Session, Message, ToolCall, ThinkingEntry, Project, RetrievalSource, User, ChatAttachment} from "@/lib/types";

interface ChatPageProps {
  initialSessions?: Session[];
  initialProjects?: Project[];
  renderedAt: string;
  user: Pick<User, "name" | "email" | "image">;
}

function generateLocalId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function deriveSessionTitleFromFirstMessage(message: string): string {
  const normalized = message.replace(/\s+/g, " ").trim();
  if (!normalized) return "New chat";
  const words = normalized.split(" ").slice(0, 12);
  return words.join(" ").slice(0, 80);
}

function extractComposerText(message: { content: unknown }): string {
  if (typeof message.content === "string") return message.content;
  if (!Array.isArray(message.content)) return "";

  return message.content
    .filter(
      (
        part
      ): part is {
        type: "text";
        text: string;
      } =>
        typeof part === "object" &&
        part !== null &&
        "type" in part &&
        "text" in part &&
        part.type === "text" &&
        typeof part.text === "string"
    )
    .map((part) => part.text)
    .join("\n");
}

export default function ChatPage({
  initialSessions = [],
  initialProjects = [],
  renderedAt,
  user,
}: ChatPageProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [sessions, setSessions] = useState<Session[]>(initialSessions);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    initialSessions.length > 0 ? initialSessions[0].id : null
  );
  const [messagesBySession, setMessagesBySession] = useState<
    Record<string, Message[]>
  >({});
  const [inputValue, setInputValue] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(
    null
  );
  const streamAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
    };
  }, []);

  // Track which sessions have had their messages loaded from DB
  const loadedSessionsRef = useRef<Set<string>>(new Set());

  // Load messages when switching to a session we haven't fetched yet
  useEffect(() => {
    if (!activeSessionId) return;
    if (loadedSessionsRef.current.has(activeSessionId)) return;

    loadedSessionsRef.current.add(activeSessionId);
    fetchMessages(activeSessionId)
      .then((msgs) => {
        setMessagesBySession((prev) => ({...prev, [activeSessionId]: msgs}));
      })
      .catch(console.error);
  }, [activeSessionId]);

  const activeMessages: Message[] = activeSessionId
    ? messagesBySession[activeSessionId] ?? []
    : [];

  const {sessionFileCount, sessionBytes} = useMemo(() => {
    const ids = new Set<string>();
    let bytes = 0;
    for (const msg of activeMessages) {
      if (msg.role !== "user") continue;
      const atts = msg.attachments ?? msg.metadata?.attachments ?? [];
      for (const att of atts) {
        if (ids.has(att.id)) continue;
        ids.add(att.id);
        bytes += att.fileSize || 0;
      }
    }
    return {sessionFileCount: ids.size, sessionBytes: bytes};
  }, [activeMessages]);

  // Update messages in React state (no localStorage, DB save happens separately)
  const updateMessages = useCallback(
    (sessionId: string, updater: (prev: Message[]) => Message[]) => {
      setMessagesBySession((prev) => {
        const current = prev[sessionId] ?? [];
        const next = updater(current);
        return {...prev, [sessionId]: next};
      });
    },
    []
  );

  const handleNewChat = useCallback(async () => {
    // If current session is already empty, just stay on it
    if (activeSessionId) {
      const currentMessages = messagesBySession[activeSessionId] ?? [];
      if (currentMessages.length === 0) return;
    }

    try {
      const newSession = await createChatSession();
      setSessions((prev) => [newSession, ...prev]);
      setMessagesBySession((prev) => ({...prev, [newSession.id]: []}));
      loadedSessionsRef.current.add(newSession.id);
      setActiveSessionId(newSession.id);
      setInputValue("");
      setPendingAttachments([]);
    } catch (err) {
      console.error("Failed to create session:", err);
    }
  }, [activeSessionId, messagesBySession]);

  const handleSelectSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setInputValue("");
    setPendingAttachments([]);
  }, []);

  const handleDeleteSession = useCallback(
    async (id: string) => {
      try {
        const {backendSessionId} = await deleteChatSession(id);
        // Also clean up Redis session
        if (backendSessionId) {
          deleteBackendSession(backendSessionId).catch(() => {});
        }
      } catch {
        // ignore errors on delete
      }

      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== id);
        return next;
      });

      setMessagesBySession((prev) => {
        const next = {...prev};
        delete next[id];
        return next;
      });
      loadedSessionsRef.current.delete(id);

      setActiveSessionId((prev) => {
        if (prev === id) {
          const remaining = sessions.filter((s) => s.id !== id);
          return remaining.length > 0 ? remaining[0].id : null;
        }
        return prev;
      });
    },
    [sessions]
  );

  const handleExportSession = useCallback(async () => {
    if (!activeSessionId) return;
    try {
      await downloadChatSessionMarkdown(activeSessionId);
    } catch (err) {
      console.error("Failed to export session:", err);
    }
  }, [activeSessionId]);

  const refreshSessions = useCallback(async () => {
    try {
      const latestSessions = await fetchSessions();
      setSessions(latestSessions);
    } catch (error) {
      console.error("Failed to refresh sessions:", error);
    }
  }, []);

  const ensureSessionTitle = useCallback((sessionId: string, title: string) => {
    if (!title || title === "New chat") return;

    setSessions((prev) =>
      prev.map((session) => {
        if (session.id !== sessionId) return session;
        return {
          ...session,
          title,
          updatedAt: new Date().toISOString(),
        };
      })
    );

    updateChatSession(sessionId, {title})
      .then(() => refreshSessions())
      .catch((error) => {
        console.error("Failed to persist session title:", error);
      });
  }, [refreshSessions]);

  const handleSignOut = useCallback(() => {
    signOut();
  }, []);

  const handleStop = useCallback(() => {
    streamAbortRef.current?.abort();
  }, []);

  const handleSubmit = useCallback(async () => {
    const content = inputValue.trim();
    if (!content || isLoading) return;

    const submittedAttachments = pendingAttachments;

    let sessionId = activeSessionId;

    // Create a new DB session if none is active
    if (!sessionId) {
      try {
        const newSession = await createChatSession();
        setSessions((prev) => [newSession, ...prev]);
        setMessagesBySession((prev) => ({...prev, [newSession.id]: []}));
        loadedSessionsRef.current.add(newSession.id);
        setActiveSessionId(newSession.id);
        sessionId = newSession.id;
      } catch (err) {
        console.error("Failed to create session:", err);
        return;
      }
    }

    const currentSessionId = sessionId;
    const persistedMessages = messagesBySession[currentSessionId] ?? [];
    const isFirstTurn = persistedMessages.length === 0;

    let backendSessionId =
      sessions.find((s) => s.id === currentSessionId)?.backendSessionId ??
      null;
    if (!backendSessionId) {
      try {
        backendSessionId = await createBackendSession();
        setSessions((prev) =>
          prev.map((s) =>
            s.id === currentSessionId ? {...s, backendSessionId} : s
          )
        );
        await updateChatSession(currentSessionId, {backendSessionId});
      } catch (err) {
        console.error("Failed to create backend session:", err);
        return;
      }
    } else {
      const exists = await backendSessionExists(backendSessionId);
      if (!exists) {
        await restoreBackendSession(
          backendSessionId,
          persistedMessages.map((message) => ({
            role: message.role,
            content: message.content,
            attachments:
              message.role === "user"
                ? message.metadata?.attachments ?? message.attachments
                : undefined,
          }))
        );
      }
    }

    // Add user message to state
    const userMessage: Message = {
      id: generateLocalId(),
      role: "user",
      content,
      parts: [{ type: "text", text: content }],
      toolCalls: [],
      thinkingEntries: [],
      sources: [],
      metadata: submittedAttachments.length > 0 ? { attachments: submittedAttachments } : {},
      attachments: submittedAttachments.length > 0 ? submittedAttachments : undefined,
      createdAt: new Date().toISOString(),
    };
    updateMessages(currentSessionId, (prev) => [...prev, userMessage]);

    setInputValue("");
    setPendingAttachments([]);
    setIsLoading(true);

    // Add assistant placeholder
    const assistantId = generateLocalId();
    const assistantMessage: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      parts: [],
      toolCalls: [],
      thinkingEntries: [],
      sources: [],
      status: { type: "running" },
      metadata: {},
      createdAt: new Date().toISOString(),
    };
    updateMessages(currentSessionId, (prev) => [...prev, assistantMessage]);
    setStreamingMessageId(assistantId);
    const abortController = new AbortController();
    streamAbortRef.current = abortController;

    try {
      // Accumulate final content for DB save
      let finalContent = "";
      let finalToolCalls: ToolCall[] = [];
      let finalThinkingEntries: ThinkingEntry[] = [];
      let finalSources: RetrievalSource[] = [];
      let finalParts = buildAssistantPartsFromLegacy(assistantMessage);
      let finalStatus = getDefaultAssistantStatus(assistantMessage) ?? { type: "running" as const };

      const markToolsDone = (entries: ThinkingEntry[]): ThinkingEntry[] =>
        entries.map((e) =>
          e.type === "tool" && e.toolCall.status === "running"
            ? { ...e, toolCall: { ...e.toolCall, status: "done" as const } }
            : e
        );
      const markToolsError = (entries: ThinkingEntry[]): ThinkingEntry[] =>
        entries.map((e) =>
          e.type === "tool" && e.toolCall.status === "running"
            ? { ...e, toolCall: { ...e.toolCall, status: "error" as const } }
            : e
        );

      await streamChat(backendSessionId, content, (event) => {
        if (event.type === "token") {
          finalContent += event.data;
          finalToolCalls = finalToolCalls.map((t) =>
            t.status === "running" ? { ...t, status: "done" as const } : t
          );
          finalThinkingEntries = markToolsDone(finalThinkingEntries);
          finalParts = appendTextPart(markRunningToolParts(finalParts, "done"), event.data);
          finalStatus = { type: "running" };
          updateMessages(currentSessionId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: m.content + event.data,
                    parts: appendTextPart(markRunningToolParts(m.parts, "done"), event.data),
                    toolCalls: m.toolCalls.map((t) =>
                      t.status === "running"
                        ? {...t, status: "done" as const}
                        : t
                    ),
                    thinkingEntries: markToolsDone(m.thinkingEntries),
                    status: { type: "running" },
                  }
                : m
            )
          );
        } else if (event.type === "thinking") {
          finalThinkingEntries = [...finalThinkingEntries, { type: "text" as const, content: event.data.content }];
          finalParts = appendReasoningPart(finalParts, event.data.content);
          updateMessages(currentSessionId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    parts: appendReasoningPart(m.parts, event.data.content),
                    thinkingEntries: [...m.thinkingEntries, { type: "text" as const, content: event.data.content }],
                    thinkingStartedAt: m.thinkingStartedAt ?? Date.now(),
                  }
                : m
            )
          );
        } else if (event.type === "tool") {
          const toolCall: ToolCall = {
            id: generateLocalId(),
            backendId: event.data.id,
            name: event.data.name,
            args: event.data.args,
            status: "running",
          };
          finalToolCalls.push(toolCall);
          finalThinkingEntries = [...finalThinkingEntries, { type: "tool" as const, toolCall }];
          finalParts = appendToolCallPart(finalParts, toolCall);
          updateMessages(currentSessionId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    parts: appendToolCallPart(m.parts, toolCall),
                    toolCalls: [...m.toolCalls, toolCall],
                    thinkingEntries: [...m.thinkingEntries, { type: "tool" as const, toolCall }],
                    thinkingStartedAt: m.thinkingStartedAt ?? Date.now(),
                  }
                : m
            )
          );
        } else if (event.type === "tool_result") {
          const backendId = event.data.id;
          const cacheHit = event.data.cache_hit === true;
          const stamp = (calls: ToolCall[]) =>
            calls.map((t) =>
              t.backendId === backendId
                ? { ...t, status: "done" as const, cacheHit }
                : t
            );
          const stampEntries = (entries: typeof finalThinkingEntries) =>
            entries.map((entry) =>
              entry.type === "tool" && entry.toolCall.backendId === backendId
                ? {
                    ...entry,
                    toolCall: {
                      ...entry.toolCall,
                      status: "done" as const,
                      cacheHit,
                    },
                  }
                : entry
            );
          finalToolCalls = stamp(finalToolCalls);
          finalThinkingEntries = stampEntries(finalThinkingEntries);
          updateMessages(currentSessionId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    toolCalls: stamp(m.toolCalls),
                    thinkingEntries: stampEntries(m.thinkingEntries),
                  }
                : m
            )
          );
        } else if (event.type === "retrieval") {
          finalSources = event.data.sources;
          finalParts = appendSourceParts(finalParts, event.data.sources);
          updateMessages(currentSessionId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    parts: appendSourceParts(m.parts, event.data.sources),
                    sources: event.data.sources,
                  }
                : m
            )
          );
        } else if (event.type === "done") {
          // Mark remaining running tools as done
          finalToolCalls = finalToolCalls.map((t) =>
            t.status === "running" ? {...t, status: "done" as const} : t
          );
          finalThinkingEntries = markToolsDone(finalThinkingEntries);
          finalParts = markRunningToolParts(finalParts, "done");
          finalStatus = { type: "complete", reason: "stop" };
          updateMessages(currentSessionId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    parts: markRunningToolParts(m.parts, "done"),
                    toolCalls: m.toolCalls.map((t) =>
                      t.status === "running"
                        ? {...t, status: "done" as const}
                        : t
                    ),
                    thinkingEntries: markToolsDone(m.thinkingEntries),
                    status: { type: "complete", reason: "stop" },
                    thinkingDuration: m.thinkingStartedAt
                      ? (Date.now() - m.thinkingStartedAt) / 1000
                      : undefined,
                  }
                : m
            )
          );
          // Bump session to top
          setSessions((prev) => {
            const nowIso = new Date().toISOString();
            return prev.map((s) => {
              if (s.id !== currentSessionId) return s;
              return {
                ...s,
                updatedAt: nowIso,
              };
            });
          });
          if (isFirstTurn) {
            ensureSessionTitle(
              currentSessionId,
              deriveSessionTitleFromFirstMessage(content)
            );
          }
        } else if (event.type === "error") {
          finalToolCalls = finalToolCalls.map((t) =>
            t.status === "running" ? { ...t, status: "error" as const } : t
          );
          finalThinkingEntries = markToolsError(finalThinkingEntries);
          finalParts = markRunningToolParts(finalParts, "error", event.data);
          finalStatus = { type: "incomplete", reason: "error", error: event.data };
          updateMessages(currentSessionId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    content: m.content || `Error: ${event.data}`,
                    parts: markRunningToolParts(m.parts, "error", event.data),
                    toolCalls: m.toolCalls.map((t) =>
                      t.status === "running"
                        ? {...t, status: "error" as const}
                        : t
                    ),
                    thinkingEntries: markToolsError(m.thinkingEntries),
                    status: { type: "incomplete", reason: "error", error: event.data },
                  }
                : m
            )
          );
        }
      }, abortController.signal, submittedAttachments);

      // Save both messages to DB after streaming completes
      // Replace local IDs with DB IDs so metadata PATCH works
      saveMessages(currentSessionId, [
        {
          role: "user",
          content,
          parts: [{ type: "text", text: content }],
          toolCalls: [],
          metadata:
            submittedAttachments.length > 0
              ? { attachments: submittedAttachments }
              : undefined,
        },
        {
          role: "assistant",
          content: finalContent,
          parts: finalParts,
          toolCalls: finalToolCalls,
          thinkingEntries: finalThinkingEntries,
          sources: finalSources,
          status: finalStatus,
        },
      ]).then((saved) => {
        if (saved.length === 2) {
          updateMessages(currentSessionId, (prev) =>
            prev.map((m) => {
              if (m.id === userMessage.id) return { ...m, dbId: saved[0].id };
              if (m.id === assistantId) return { ...m, dbId: saved[1].id };
              return m;
            })
          );
        }
      }).catch(console.error);
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        updateMessages(currentSessionId, (prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  parts: markRunningToolParts(m.parts, "error", "Cancelled"),
                  toolCalls: m.toolCalls.map((t) =>
                    t.status === "running" ? {...t, status: "error" as const} : t
                  ),
                  thinkingEntries: m.thinkingEntries.map((e) =>
                    e.type === "tool" && e.toolCall.status === "running"
                      ? { ...e, toolCall: { ...e.toolCall, status: "error" as const } }
                      : e
                  ),
                  status: { type: "incomplete", reason: "cancelled" },
                }
              : m
          )
        );
        return;
      }
      const message =
        err instanceof Error ? err.message : "Unknown error occurred";
      updateMessages(currentSessionId, (prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content: m.content || `Failed to get response: ${message}`,
                parts: markRunningToolParts(m.parts, "error", message),
                toolCalls: m.toolCalls.map((t) =>
                  t.status === "running" ? {...t, status: "error" as const} : t
                ),
                thinkingEntries: m.thinkingEntries.map((e) =>
                  e.type === "tool" && e.toolCall.status === "running"
                    ? { ...e, toolCall: { ...e.toolCall, status: "error" as const } }
                    : e
                ),
                status: { type: "incomplete", reason: "error", error: message },
              }
            : m
        )
      );
    } finally {
      if (streamAbortRef.current === abortController) {
        streamAbortRef.current = null;
      }
      setIsLoading(false);
      setStreamingMessageId(null);
    }
  }, [inputValue, pendingAttachments, isLoading, activeSessionId, sessions, messagesBySession, updateMessages, ensureSessionTitle]);

  // ─── assistant-ui ExternalStoreRuntime ───
  // Bridge our message state to assistant-ui's runtime so its primitives
  // (Thread, ActionBar, etc.) can read from our existing state.
  const runtime = useExternalStoreRuntime({
    messages: activeMessages,
    isRunning: isLoading,
    convertMessage,
    onNew: async (message) => {
      const text = extractComposerText(message);
      if (text) {
        setInputValue(text);
        // Use a microtask so inputValue state updates before handleSubmit reads it
        await Promise.resolve();
        handleSubmit();
      }
    },
  });

  return (
    <div className='flex h-screen w-screen overflow-hidden bg-[#1a1a1a] text-zinc-100'>
      {/* Sidebar */}
      <div
        className={`shrink-0 transition-all duration-200 ease-in-out overflow-hidden ${
          sidebarOpen ? "w-[260px]" : "w-0"
        }`}
        aria-hidden={!sidebarOpen}>
        <div className='w-[260px] h-full'>
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onNewChat={handleNewChat}
          onDeleteSession={handleDeleteSession}
          initialProjects={initialProjects}
          referenceTime={renderedAt}
          user={user}
          onSignOut={handleSignOut}
        />
        </div>
      </div>

      {/* Main content */}
      <main className='flex flex-col flex-1 min-w-0 min-h-0'>
        {/* Top bar */}
        <header className='flex items-center gap-2 px-4 py-3 shrink-0 border-b border-white/6'>
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            aria-expanded={sidebarOpen}
            className='p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100'>
            {sidebarOpen ? (
              <CaretLeft size={18} aria-hidden='true' />
            ) : (
              <CaretRight size={18} aria-hidden='true' />
            )}
          </button>
          <div className='flex-1 flex items-center justify-center'>
            <span className='text-sm font-medium text-zinc-400 truncate max-w-xs'>
              {activeSessionId
                ? sessions.find((s) => s.id === activeSessionId)?.title ||
                  "New chat"
                : "RunaxAI"}
            </span>
          </div>
          <div className='flex items-center gap-1'>
            <button
              onClick={() => setMemoryOpen(true)}
              aria-label='View memory'
              title='Memory'
              className='p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100'>
              <Brain size={18} weight="duotone" aria-hidden='true' />
            </button>
            <button
              onClick={handleNewChat}
              aria-label='New chat'
              className='p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100'>
              <PencilSimpleLineIcon size={18} aria-hidden='true' />
            </button>
            <button
              onClick={handleExportSession}
              aria-label='Export chat'
              disabled={!activeSessionId}
              className='p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100 disabled:opacity-40 disabled:cursor-not-allowed'>
              <DownloadSimple size={18} aria-hidden='true' />
            </button>
          </div>
        </header>

        {/* Chat area */}
        <AssistantRuntimeProvider runtime={runtime}>
          <div className='relative flex flex-col flex-1 min-h-0'>
            <ChatArea
              messages={activeMessages}
              streamingMessageId={streamingMessageId}
              isLoading={isLoading}
              isStreaming={streamingMessageId !== null}
              inputValue={inputValue}
              onInputChange={setInputValue}
              onSubmit={handleSubmit}
              onStop={handleStop}
              attachments={pendingAttachments}
              onAttachmentsChange={setPendingAttachments}
              sessionFileCount={sessionFileCount}
              sessionBytes={sessionBytes}
            />
          </div>
        </AssistantRuntimeProvider>
      </main>

      <MemoryPanel open={memoryOpen} onClose={() => setMemoryOpen(false)} />
    </div>
  );
}
