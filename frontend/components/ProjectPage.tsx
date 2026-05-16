"use client";

import {useState, useCallback, useEffect, useRef} from "react";
import {signOut} from "@/lib/api";
import {CaretLeft} from "@phosphor-icons/react/dist/ssr/CaretLeft";
import {CaretRight} from "@phosphor-icons/react/dist/ssr/CaretRight";
import {ArrowLeft} from "@phosphor-icons/react/dist/ssr/ArrowLeft";
import {DownloadSimple} from "@phosphor-icons/react/dist/ssr/DownloadSimple";
import ProjectSidebar from "@/components/ProjectSidebar";
import ChatArea from "@/components/ChatArea";
import {
  backendSessionExists,
  fetchAgents,
  uploadDocument,
  reingestDocument,
  deleteDocument,
  downloadChatSessionMarkdown,
  getDocumentDownloadUrl,
  pollDocumentStatus,
  createProjectSession,
  deleteProjectSession,
  restoreBackendSession,
  searchProjectDocuments,
  streamProjectChat,
  updateChatSession,
  fetchProjectSessions,
  fetchMessages,
  saveMessages,
} from "@/lib/api";
import type {
  Project,
  Session,
  Message,
  AgentInfo,
  ToolCall,
  ThinkingEntry,
  RetrievalSource,
  ProjectSearchResult,
  User,
} from "@/lib/types";
import Link from "next/link";
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
} from "@assistant-ui/react";
import {convertMessage} from "@/lib/chatRuntime";
import {
  appendDataPart,
  appendReasoningPart,
  appendSourceParts,
  appendTextPart,
  appendToolCallPart,
  buildAssistantPartsFromLegacy,
  getDefaultAssistantStatus,
  markRunningToolParts,
} from "@/lib/messageParts";

interface ProjectPageProps {
  initialProject: Project;
  initialSessions: Session[];
  projectId: string;
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

function extractComposerText(message: {content: unknown}): string {
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

export default function ProjectPage({
  initialProject,
  initialSessions = [],
  projectId,
  user,
}: ProjectPageProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [project, setProject] = useState<Project>(initialProject);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  // Session management (mirrors ChatPage pattern)
  const [sessions, setSessions] = useState<Session[]>(initialSessions);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    initialSessions.length > 0 ? initialSessions[0].id : null
  );
  const [messagesBySession, setMessagesBySession] = useState<
    Record<string, Message[]>
  >({});

  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [reingestingDocumentId, setReingestingDocumentId] = useState<string | null>(null);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(
    null
  );
  const streamAbortRef = useRef<AbortController | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<ProjectSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const loadedSessionsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
    };
  }, []);

  // Load agents on mount (project and sessions are already loaded via SSR)
  useEffect(() => {
    fetchAgents().then(setAgents).catch(console.error);
  }, []);

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

  const handleStop = useCallback(() => {
    streamAbortRef.current?.abort();
  }, []);

  // Poll processing documents
  useEffect(() => {
    if (!project) return;
    const processingDocs = project.documents.filter(
      (d) => d.status === "processing" || d.status === "uploading"
    );
    if (processingDocs.length === 0) return;

    const interval = setInterval(async () => {
      let changed = false;
      const updatedDocs = await Promise.all(
        project.documents.map(async (doc) => {
          if (doc.status !== "processing" && doc.status !== "uploading")
            return doc;
          try {
            const status = await pollDocumentStatus(projectId, doc.id);
            if (status.status !== doc.status) {
              changed = true;
              return {
                ...doc,
                status: status.status as typeof doc.status,
                chunkCount: status.chunkCount,
                chunkStrategy: status.chunkStrategy,
                errorMessage: status.errorMessage,
              };
            }
          } catch {
            // ignore
          }
          return doc;
        })
      );
      if (changed) {
        setProject((prev) => (prev ? {...prev, documents: updatedDocs} : prev));
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [project, projectId]);

  const handleUploadFile = useCallback(
    async (file: File) => {
      if (!project) return;
      setIsUploading(true);
      try {
        const doc = await uploadDocument(projectId, file);
        setProject((prev) =>
          prev ? {...prev, documents: [doc, ...prev.documents]} : prev
        );
      } catch (err) {
        console.error("Upload failed:", err);
      } finally {
        setIsUploading(false);
      }
    },
    [project, projectId]
  );

  const handleDeleteDocument = useCallback(
    async (docId: string) => {
      try {
        await deleteDocument(projectId, docId);
        setProject((prev) =>
          prev
            ? {...prev, documents: prev.documents.filter((d) => d.id !== docId)}
            : prev
        );
      } catch (err) {
        console.error("Delete failed:", err);
      }
    },
    [projectId]
  );

  const handleReingestDocument = useCallback(
    async (docId: string, file: File) => {
      setReingestingDocumentId(docId);
      try {
        const doc = await reingestDocument(projectId, docId, file);
        setProject((prev) =>
          prev
            ? {
                ...prev,
                documents: prev.documents.map((existing) =>
                  existing.id === doc.id ? doc : existing
                ),
              }
            : prev
        );
      } catch (err) {
        console.error("Re-ingest failed:", err);
      } finally {
        setReingestingDocumentId(null);
      }
    },
    [projectId]
  );

  const handleSearch = useCallback(async () => {
    const query = searchQuery.trim();
    if (!query) {
      setSearchResults([]);
      return;
    }

    setIsSearching(true);
    try {
      const results = await searchProjectDocuments(projectId, query, 5);
      setSearchResults(results);
    } catch (err) {
      console.error("Project search failed:", err);
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  }, [projectId, searchQuery]);

  const handleSignOut = useCallback(() => {
    signOut();
  }, []);

  const handleClearSearch = useCallback(() => {
    setSearchQuery("");
    setSearchResults([]);
  }, []);

  const handleOpenSearchResult = useCallback(
    async (result: ProjectSearchResult) => {
      if (!result.documentId) return;
      try {
        const url = await getDocumentDownloadUrl(projectId, result.documentId);
        window.open(url, "_blank", "noopener,noreferrer");
      } catch (err) {
        console.error("Failed to open search result:", err);
      }
    },
    [projectId]
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
      const latestSessions = await fetchProjectSessions(projectId);
      setSessions(latestSessions);
    } catch (error) {
      console.error("Failed to refresh project sessions:", error);
    }
  }, [projectId]);

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
        console.error("Failed to persist project session title:", error);
      });
  }, [refreshSessions]);

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
    // If current session is already empty, stay on it
    if (activeSessionId) {
      const currentMessages = messagesBySession[activeSessionId] ?? [];
      if (currentMessages.length === 0) return;
    }

    try {
      const newSession = await createProjectSession(projectId);
      setSessions((prev) => [newSession, ...prev]);
      setMessagesBySession((prev) => ({...prev, [newSession.id]: []}));
      loadedSessionsRef.current.add(newSession.id);
      setActiveSessionId(newSession.id);
      setInputValue("");
    } catch (err) {
      console.error("Failed to create session:", err);
    }
  }, [activeSessionId, messagesBySession, projectId]);

  const handleSelectSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setInputValue("");
  }, []);

  const handleDeleteSession = useCallback(
    async (id: string) => {
      try {
        await deleteProjectSession(projectId, id);
      } catch {
        // ignore
      }

      setSessions((prev) => prev.filter((s) => s.id !== id));
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
    [sessions, projectId]
  );

  const handleSubmit = useCallback(async () => {
    const content = inputValue.trim();
    if (!content || isLoading || !project) return;

    let sessionId = activeSessionId;
    let currentSession = sessions.find((s) => s.id === sessionId);

    // Create a new project session if none is active
    if (!sessionId) {
      try {
        const newSession = await createProjectSession(projectId);
        setSessions((prev) => [newSession, ...prev]);
        setMessagesBySession((prev) => ({...prev, [newSession.id]: []}));
        loadedSessionsRef.current.add(newSession.id);
        setActiveSessionId(newSession.id);
        sessionId = newSession.id;
        currentSession = newSession;
      } catch (err) {
        console.error("Failed to create project session:", err);
        return;
      }
    }

    const currentSessionId = sessionId;
    const persistedMessages = messagesBySession[currentSessionId] ?? [];
    const isFirstTurn = persistedMessages.length === 0;
    const backendSessionId = currentSession?.backendSessionId;

    if (!backendSessionId) {
      console.error("No backend session ID found");
      return;
    }

    const exists = await backendSessionExists(backendSessionId);
    if (!exists) {
      await restoreBackendSession(
        backendSessionId,
        persistedMessages.map((message) => ({
          role: message.role,
          content: message.content,
        })),
        project.name
      );
    }

    // Add user message
    const userMessage: Message = {
      id: generateLocalId(),
      role: "user",
      content,
      parts: [{type: "text", text: content}],
      toolCalls: [],
      thinkingEntries: [],
      sources: [],
      metadata: {},
      createdAt: new Date().toISOString(),
    };
    updateMessages(currentSessionId, (prev) => [...prev, userMessage]);

    setInputValue("");
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
      status: {type: "running"},
      metadata: {},
      createdAt: new Date().toISOString(),
    };
    updateMessages(currentSessionId, (prev) => [...prev, assistantMessage]);
    setStreamingMessageId(assistantId);
    const abortController = new AbortController();
    streamAbortRef.current = abortController;

    try {
      let finalContent = "";
      let detectedAgent = "";
      let finalToolCalls: ToolCall[] = [];
      let finalThinkingEntries: ThinkingEntry[] = [];
      let finalSources: RetrievalSource[] = [];
      let finalParts = buildAssistantPartsFromLegacy(assistantMessage);
      let finalStatus = getDefaultAssistantStatus(assistantMessage) ?? {
        type: "running" as const,
      };

      await streamProjectChat(
        projectId,
        backendSessionId,
        content,
        (event) => {
          const markToolsDone = (entries: ThinkingEntry[]): ThinkingEntry[] =>
            entries.map((e) =>
              e.type === "tool" && e.toolCall.status === "running"
                ? {...e, toolCall: {...e.toolCall, status: "done" as const}}
                : e
            );
          const markToolsError = (entries: ThinkingEntry[]): ThinkingEntry[] =>
            entries.map((e) =>
              e.type === "tool" && e.toolCall.status === "running"
                ? {...e, toolCall: {...e.toolCall, status: "error" as const}}
                : e
            );

          if (event.type === "token") {
            finalContent += event.data;
            finalParts = appendTextPart(finalParts, event.data);
            finalStatus = {type: "running"};
            updateMessages(currentSessionId, (prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      content: m.content + event.data,
                      parts: appendTextPart(m.parts, event.data),
                      status: {type: "running"},
                    }
                  : m
              )
            );
          } else if (event.type === "thinking") {
            finalThinkingEntries = [
              ...finalThinkingEntries,
              {type: "text" as const, content: event.data.content},
            ];
            finalParts = appendReasoningPart(finalParts, event.data.content);
            updateMessages(currentSessionId, (prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      parts: appendReasoningPart(m.parts, event.data.content),
                      thinkingEntries: [
                        ...m.thinkingEntries,
                        {type: "text" as const, content: event.data.content},
                      ],
                      thinkingStartedAt: m.thinkingStartedAt ?? Date.now(),
                    }
                  : m
              )
            );
          } else if (event.type === "agent") {
            detectedAgent = event.data.name;
            const agentTool: ToolCall = {
              id: generateLocalId(),
              name: `${event.data.name} agent`,
              args: {description: event.data.description},
              status: "running",
            };
            finalToolCalls = [...finalToolCalls, agentTool];
            finalThinkingEntries = [
              ...finalThinkingEntries,
              {type: "tool" as const, toolCall: agentTool},
            ];
            finalParts = appendDataPart(
              appendToolCallPart(finalParts, agentTool),
              "agent",
              {name: event.data.name, description: event.data.description}
            );
            updateMessages(currentSessionId, (prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      agentName: event.data.name,
                      parts: appendDataPart(
                        appendToolCallPart(m.parts, agentTool),
                        "agent",
                        {
                          name: event.data.name,
                          description: event.data.description,
                        }
                      ),
                      toolCalls: [...m.toolCalls, agentTool],
                      thinkingEntries: [
                        ...m.thinkingEntries,
                        {type: "tool" as const, toolCall: agentTool},
                      ],
                      thinkingStartedAt: m.thinkingStartedAt ?? Date.now(),
                    }
                  : m
              )
            );
          } else if (event.type === "tool") {
            const toolCall: ToolCall = {
              id: generateLocalId(),
              name: event.data.name,
              args: event.data.args,
              status: "running",
            };
            finalToolCalls = [...finalToolCalls, toolCall];
            finalThinkingEntries = [
              ...finalThinkingEntries,
              {type: "tool" as const, toolCall},
            ];
            finalParts = appendToolCallPart(finalParts, toolCall);
            updateMessages(currentSessionId, (prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      parts: appendToolCallPart(m.parts, toolCall),
                      toolCalls: [...m.toolCalls, toolCall],
                      thinkingEntries: [
                        ...m.thinkingEntries,
                        {type: "tool" as const, toolCall},
                      ],
                      thinkingStartedAt: m.thinkingStartedAt ?? Date.now(),
                    }
                  : m
              )
            );
          } else if (event.type === "retrieval") {
            const cacheHit = event.data.cache_hit === true;
            const retrievalTool: ToolCall = {
              id: generateLocalId(),
              name: cacheHit
                ? `searched ${event.data.count} passages (cached)`
                : `searched ${event.data.count} passages`,
              status: "done",
            };
            finalSources = event.data.sources;
            finalToolCalls = finalToolCalls
              .map((t) =>
                t.status === "running" ? {...t, status: "done" as const} : t
              )
              .concat(retrievalTool);
            finalThinkingEntries = markToolsDone(finalThinkingEntries).concat({
              type: "tool" as const,
              toolCall: retrievalTool,
            });
            finalParts = appendSourceParts(
              appendToolCallPart(
                markRunningToolParts(finalParts, "done"),
                retrievalTool
              ),
              event.data.sources
            );
            updateMessages(currentSessionId, (prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      parts: appendSourceParts(
                        appendToolCallPart(
                          markRunningToolParts(m.parts, "done"),
                          retrievalTool
                        ),
                        event.data.sources
                      ),
                      toolCalls: m.toolCalls
                        .map((t) =>
                          t.status === "running"
                            ? {...t, status: "done" as const}
                            : t
                        )
                        .concat(retrievalTool),
                      thinkingEntries: markToolsDone(m.thinkingEntries).concat({
                        type: "tool" as const,
                        toolCall: retrievalTool,
                      }),
                      sources: event.data.sources,
                      sourcesCached: cacheHit,
                    }
                  : m
              )
            );
          } else if (event.type === "done") {
            finalToolCalls = finalToolCalls.map((t) =>
              t.status === "running" ? {...t, status: "done" as const} : t
            );
            finalThinkingEntries = markToolsDone(finalThinkingEntries);
            finalParts = markRunningToolParts(finalParts, "done");
            finalStatus = {type: "complete", reason: "stop"};
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
                      status: {type: "complete", reason: "stop"},
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
              t.status === "running" ? {...t, status: "error" as const} : t
            );
            finalThinkingEntries = markToolsError(finalThinkingEntries);
            finalParts = markRunningToolParts(finalParts, "error", event.data);
            finalStatus = {
              type: "incomplete",
              reason: "error",
              error: event.data,
            };
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
                      thinkingEntries: m.thinkingEntries.map((e) =>
                        e.type === "tool" && e.toolCall.status === "running"
                          ? {
                              ...e,
                              toolCall: {
                                ...e.toolCall,
                                status: "error" as const,
                              },
                            }
                          : e
                      ),
                      status: {
                        type: "incomplete",
                        reason: "error",
                        error: event.data,
                      },
                    }
                  : m
              )
            );
          }
        },
        selectedAgent,
        abortController.signal
      );

      // Save messages to DB (persist agentName in metadata for session restore)
      // Replace local IDs with DB IDs so PATCH for quiz state works
      saveMessages(currentSessionId, [
        {
          role: "user",
          content,
          parts: [{type: "text", text: content}],
          toolCalls: [],
        },
        {
          role: "assistant",
          content: finalContent,
          parts: finalParts,
          toolCalls: finalToolCalls,
          thinkingEntries: finalThinkingEntries,
          sources: finalSources,
          status: finalStatus,
          agentName: detectedAgent || undefined,
          metadata: detectedAgent ? {agentName: detectedAgent} : undefined,
        },
      ])
        .then((saved) => {
          if (saved.length === 2) {
            updateMessages(currentSessionId, (prev) =>
              prev.map((m) => {
                if (m.id === userMessage.id) return {...m, dbId: saved[0].id};
                if (m.id === assistantId) return {...m, dbId: saved[1].id};
                return m;
              })
            );
          }
        })
        .catch(console.error);
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
                      ? {
                          ...e,
                          toolCall: {...e.toolCall, status: "error" as const},
                        }
                      : e
                  ),
                  status: {type: "incomplete", reason: "cancelled"},
                }
              : m
          )
        );
        return;
      }
      const message = err instanceof Error ? err.message : "Unknown error";
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
                    ? {
                        ...e,
                        toolCall: {...e.toolCall, status: "error" as const},
                      }
                    : e
                ),
                status: {type: "incomplete", reason: "error", error: message},
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
  }, [
    inputValue,
    isLoading,
    project,
    projectId,
    selectedAgent,
    activeSessionId,
    sessions,
    messagesBySession,
    updateMessages,
    ensureSessionTitle,
  ]);

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
      {/* Project sidebar */}
      <div
        className={`shrink-0 transition-all duration-200 ease-in-out overflow-hidden ${
          sidebarOpen ? "w-[280px]" : "w-0"
        }`}
        aria-hidden={!sidebarOpen}>
        <div className='w-[280px] h-full'>
          <ProjectSidebar
            project={project}
            agents={agents}
            selectedAgent={selectedAgent}
            onSelectAgent={setSelectedAgent}
            onUploadFile={handleUploadFile}
            onReingestDocument={handleReingestDocument}
            onDeleteDocument={handleDeleteDocument}
            isUploading={isUploading}
            reingestingDocumentId={reingestingDocumentId}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            onSearch={handleSearch}
            onClearSearch={handleClearSearch}
            searchResults={searchResults}
            isSearching={isSearching}
            onOpenSearchResult={handleOpenSearchResult}
            sessions={sessions}
            activeSessionId={activeSessionId}
            onSelectSession={handleSelectSession}
            onNewChat={handleNewChat}
            onDeleteSession={handleDeleteSession}
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
            className='p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100'>
            {sidebarOpen ? (
              <CaretLeft size={18} aria-hidden='true' />
            ) : (
              <CaretRight size={18} aria-hidden='true' />
            )}
          </button>

          <Link
            href='/chat'
            className='p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100'
            aria-label='Back to chats'>
            <ArrowLeft size={18} aria-hidden='true' />
          </Link>

          <div className='flex-1 flex items-center justify-center'>
            <span className='text-sm font-medium text-zinc-400 truncate max-w-xs'>
              {project.name}
            </span>
            {selectedAgent && (
              <span className='ml-2 px-2 py-0.5 text-[11px] rounded-full bg-violet-500/15 text-violet-400 border border-violet-500/20 capitalize'>
                {selectedAgent}
              </span>
            )}
          </div>

          <button
            onClick={handleExportSession}
            aria-label='Export chat'
            disabled={!activeSessionId}
            className='p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100 disabled:opacity-40 disabled:cursor-not-allowed'>
            <DownloadSimple size={18} aria-hidden='true' />
          </button>
        </header>

        {/* Chat area */}
        <div className='relative flex flex-col flex-1 min-h-0'>
          <AssistantRuntimeProvider runtime={runtime}>
            <ChatArea
              messages={activeMessages}
              streamingMessageId={streamingMessageId}
              isLoading={isLoading}
              isStreaming={streamingMessageId !== null}
              inputValue={inputValue}
              onInputChange={setInputValue}
              onSubmit={handleSubmit}
              onStop={handleStop}
              projectId={projectId}
              projectDocuments={project.documents}
            />
          </AssistantRuntimeProvider>
        </div>
      </main>
    </div>
  );
}
