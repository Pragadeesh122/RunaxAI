import type {
  AssistantMessageStatus,
  ChatAttachment,
  Message,
  MessageMetadata,
  MemoryFact,
  MessagePart,
  Project,
  ProjectDocument,
  RetrievalSource,
  Session,
  AgentInfo,
  UserMemory,
  ProjectSearchResult,
} from "./types";
import {
  buildAssistantPartsFromLegacy,
  deriveSourcesFromParts,
  deriveThinkingEntriesFromParts,
  deriveToolCallsFromParts,
  extractTextFromParts,
  getDefaultAssistantStatus,
} from "./messageParts";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";

export async function apiFetch(endpoint: string, options: RequestInit = {}) {
  const url = endpoint.startsWith("http")
    ? endpoint
    : `${API_BASE_URL}${endpoint.replace(/^\/api/, "")}`;
  const modifiedOptions = {
    ...options,
    credentials: "include" as RequestCredentials,
  };
  return fetch(url, modifiedOptions);
}

// ─── Python backend (proxied or direct) ───

export async function signOut() {
  await apiFetch("/auth/logout", {method: "POST"});
  // Make post-logout navigation explicit instead of relying on page guards after reload.
  window.location.href = "/";
}

export async function loginWithCredentials(
  email: string,
  password: string
): Promise<void> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);

  const res = await apiFetch("/auth/login", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded"},
    body,
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to sign in");
  }
}

export async function registerWithCredentials(
  email: string,
  password: string
): Promise<void> {
  const res = await apiFetch("/auth/register", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({email, password}),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to create account");
  }
}

export async function requestPasswordReset(email: string): Promise<void> {
  const res = await apiFetch("/auth/forgot-password", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({email}),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to request password reset");
  }
}

export async function resetPassword(
  token: string,
  password: string
): Promise<void> {
  const res = await apiFetch("/auth/reset-password", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({token, password}),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to reset password");
  }
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<void> {
  const res = await apiFetch("/auth/change-password", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || "Failed to change password");
  }
}

export async function createBackendSession(): Promise<string> {
  const res = await apiFetch("/api/chat/backend-session", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
  });
  if (!res.ok) throw new Error(`Failed to create session: ${res.status}`);
  const data = await res.json();
  return data.session_id;
}

export async function deleteBackendSession(sessionId: string): Promise<void> {
  await apiFetch(`/api/chat/backend-session/${sessionId}`, {method: "DELETE"});
}

export async function backendSessionExists(
  sessionId: string
): Promise<boolean> {
  const res = await apiFetch(`/session/${sessionId}/exists`);
  if (!res.ok) return false;
  const data = await res.json();
  return data.exists === true;
}

export async function restoreBackendSession(
  sessionId: string,
  messages: Array<{role: string; content: string; attachments?: ChatAttachment[]}>,
  projectName?: string
): Promise<void> {
  const res = await apiFetch("/session/restore", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      session_id: sessionId,
      messages,
      project_name: projectName ?? null,
    }),
  });
  if (!res.ok) throw new Error("Failed to restore backend session");
}

export type SSEEvent =
  | {type: "token"; data: string}
  | {type: "tool"; data: {name: string; args?: Record<string, unknown>; id?: string}}
  | {type: "tool_result"; data: {id: string; name: string; cache_hit?: boolean}}
  | {type: "thinking"; data: {content: string}}
  | {type: "agent"; data: {name: string; description: string}}
  | {type: "retrieval"; data: {sources: RetrievalSource[]; count: number; cache_hit?: boolean}}
  | {type: "error"; data: string}
  | {
      type: "done";
      data: {
        tools_used?: string[];
        sources_used?: number;
        agent?: string;
        structured?: boolean;
        prompt_tokens: number;
      };
    };

export const CHAT_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024;
export const CHAT_ATTACHMENT_MAX_COUNT = 5;
export const CHAT_SESSION_MAX_FILES = 10;
export const CHAT_SESSION_MAX_BYTES = 20 * 1024 * 1024;
export const CHAT_ATTACHMENT_ALLOWED_MIME = new Set<string>([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "application/pdf",
  "text/plain",
  "text/markdown",
  "text/csv",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]);
export const CHAT_ATTACHMENT_ALLOWED_EXTS = new Set<string>([
  "png", "jpg", "jpeg", "webp", "gif",
  "pdf", "txt", "md", "csv", "docx",
]);

export function isAllowedChatAttachment(file: File): boolean {
  if (CHAT_ATTACHMENT_ALLOWED_MIME.has(file.type)) return true;
  const ext = file.name.includes(".")
    ? file.name.split(".").pop()!.toLowerCase()
    : "";
  return CHAT_ATTACHMENT_ALLOWED_EXTS.has(ext);
}

export async function uploadChatAttachment(file: File): Promise<ChatAttachment> {
  const initRes = await apiFetch("/api/chat/upload", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      filename: file.name,
      fileSize: file.size,
      mimeType: file.type,
    }),
  });
  if (!initRes.ok) {
    const err = await initRes.json().catch(() => ({error: "Upload failed"}));
    throw new Error(err.detail || err.error || "Upload failed");
  }
  const data = await initRes.json();
  const {uploadUrl, ...attachment} = data as ChatAttachment & {uploadUrl: string};

  const putRes = await fetch(uploadUrl, {
    method: "PUT",
    mode: "cors",
    body: file,
  });
  if (!putRes.ok) {
    const detail = await putRes.text().catch(() => "");
    throw new Error(
      `Direct upload to storage failed (${putRes.status}): ${detail.slice(0, 300)}`
    );
  }

  return attachment;
}

export async function getChatAttachmentUrl(storageKey: string): Promise<string> {
  const res = await apiFetch(
    `/api/chat/attachments/url?key=${encodeURIComponent(storageKey)}`
  );
  if (!res.ok) throw new Error("Failed to get attachment URL");
  const data = await res.json();
  return data.url;
}

export async function streamChat(
  sessionId: string,
  message: string,
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
  attachments?: ChatAttachment[]
): Promise<void> {
  const res = await apiFetch("/api/chat/stream", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      sessionId,
      message,
      attachments: attachments ?? [],
    }),
    signal,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Chat request failed: ${res.status} ${text}`);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});

    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const lines = part.split("\n");
      let eventType = "";
      const dataLines: string[] = [];

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          dataLines.push(line.slice(6));
        }
      }

      const eventData = dataLines.join("\n");
      if (!eventType || dataLines.length === 0) continue;

      if (eventType === "token") {
        onEvent({type: "token", data: eventData});
      } else if (eventType === "tool") {
        try {
          onEvent({type: "tool", data: JSON.parse(eventData)});
        } catch {
          // ignore malformed tool event
        }
      } else if (eventType === "tool_result") {
        try {
          onEvent({type: "tool_result", data: JSON.parse(eventData)});
        } catch {
          // ignore malformed tool_result event
        }
      } else if (eventType === "thinking") {
        try {
          onEvent({type: "thinking", data: JSON.parse(eventData)});
        } catch {
          // ignore malformed thinking event
        }
      } else if (eventType === "retrieval") {
        try {
          onEvent({type: "retrieval", data: JSON.parse(eventData)});
        } catch {
          // ignore malformed retrieval event
        }
      } else if (eventType === "error") {
        onEvent({type: "error", data: eventData});
      } else if (eventType === "done") {
        try {
          onEvent({type: "done", data: JSON.parse(eventData)});
        } catch {
          onEvent({type: "done", data: {tools_used: [], prompt_tokens: 0}});
        }
      }
    }
  }
}

// ─── FastAPI session + message persistence ───

export async function fetchSessions(): Promise<Session[]> {
  const res = await apiFetch("/api/chat/sessions");
  if (!res.ok) return [];
  return res.json();
}

export async function createChatSession(title?: string): Promise<Session> {
  const res = await apiFetch("/api/chat/sessions", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({title}),
  });
  if (!res.ok) throw new Error("Failed to create chat session");
  return res.json();
}

export async function updateChatSession(
  id: string,
  data: {title?: string; backendSessionId?: string}
): Promise<void> {
  await apiFetch(`/api/chat/sessions/${id}`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data),
  });
}

export async function deleteChatSession(
  id: string
): Promise<{backendSessionId: string | null}> {
  const res = await apiFetch(`/api/chat/sessions/${id}`, {method: "DELETE"});
  if (!res.ok) throw new Error("Failed to delete session");
  return res.json();
}

export async function fetchMessages(sessionId: string): Promise<Message[]> {
  const res = await apiFetch(`/api/chat/sessions/${sessionId}/messages`);
  if (!res.ok) return [];
  const messages: Array<{
    id: string;
    role: Message["role"];
    content: string;
    toolCalls?: Message["toolCalls"];
    parts?: MessagePart[];
    status?: AssistantMessageStatus;
    thinkingEntries?: Message["thinkingEntries"];
    sources?: RetrievalSource[];
    metadata?: MessageMetadata;
    agentName?: string;
    createdAt: string;
  }> = await res.json();

  return messages.map((message) => {
    const metadata = message.metadata ?? {};
    const parts =
      message.parts ??
      buildAssistantPartsFromLegacy({
        content: message.content,
        toolCalls: message.toolCalls ?? [],
        thinkingEntries: message.thinkingEntries ?? [],
        sources: message.sources ?? [],
      });

    const toolCalls = message.toolCalls ?? deriveToolCallsFromParts(parts);
    const thinkingEntries =
      message.thinkingEntries ?? deriveThinkingEntriesFromParts(parts);
    const sources = message.sources ?? deriveSourcesFromParts(parts);

    return {
      ...message,
      content: message.content || extractTextFromParts(parts),
      parts,
      toolCalls,
      thinkingEntries,
      sources,
      status:
        message.status ??
        getDefaultAssistantStatus({
          role: message.role,
          content: message.content || extractTextFromParts(parts),
        }),
      metadata,
      agentName: message.agentName ?? metadata.agentName,
    };
  });
}

export async function downloadChatSessionMarkdown(
  sessionId: string
): Promise<void> {
  const res = await apiFetch(`/api/chat/sessions/${sessionId}/export`);
  if (!res.ok) throw new Error("Failed to export session");

  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") || "";
  const filenameMatch = disposition.match(/filename="([^"]+)"/i);
  const filename = filenameMatch?.[1] || "chat-session.md";

  const downloadUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = downloadUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(downloadUrl);
}

export async function saveMessages(
  sessionId: string,
  messages: Array<{
    role: string;
    content: string;
    toolCalls?: unknown[];
    parts?: MessagePart[];
    status?: AssistantMessageStatus;
    thinkingEntries?: Message["thinkingEntries"];
    sources?: RetrievalSource[];
    agentName?: string;
    metadata?: Record<string, unknown>;
  }>
): Promise<Array<{id: string; role: string}>> {
  const res = await apiFetch(`/api/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(messages),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return data.messages ?? [];
}

export async function updateMessageMetadata(
  messageId: string,
  metadata: Record<string, unknown>
): Promise<void> {
  const res = await apiFetch(`/api/chat/messages/${messageId}`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({metadata}),
  });
  if (!res.ok) throw new Error("Failed to update message metadata");
}

// ─── Projects API ───

export async function fetchProjects(): Promise<Project[]> {
  const res = await apiFetch("/api/projects");
  if (!res.ok) return [];
  return res.json();
}

export async function createProject(
  name: string,
  description?: string
): Promise<Project> {
  const res = await apiFetch("/api/projects", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name, description}),
  });
  if (!res.ok) throw new Error("Failed to create project");
  return res.json();
}

export async function fetchProject(id: string): Promise<Project> {
  const res = await apiFetch(`/api/projects/${id}`);
  if (!res.ok) throw new Error("Failed to fetch project");
  return res.json();
}

export async function updateProject(
  id: string,
  data: {name?: string; description?: string; status?: string}
): Promise<void> {
  await apiFetch(`/api/projects/${id}`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data),
  });
}

export async function deleteProject(id: string): Promise<void> {
  await apiFetch(`/api/projects/${id}`, {method: "DELETE"});
}

export async function uploadDocument(
  projectId: string,
  file: File
): Promise<ProjectDocument> {
  // 1. Create DB record + receive a scoped presigned upload URL.
  const initRes = await apiFetch(`/api/projects/${projectId}/upload`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({filename: file.name, fileSize: file.size}),
  });
  if (!initRes.ok) {
    const err = await initRes.json().catch(() => ({error: "Upload failed"}));
    throw new Error(err.detail || err.error || "Upload failed");
  }

  const {uploadUrl, ...document} = await initRes.json();

  // 2. Upload file directly to object storage. No cookies should be sent.
  const uploadRes = await fetch(uploadUrl, {
    method: "PUT",
    mode: "cors",
    body: file,
  });
  if (!uploadRes.ok) {
    const detail = await uploadRes.text().catch(() => "");
    throw new Error(
      `Direct upload to storage failed (${uploadRes.status}): ${detail.slice(
        0,
        300
      )}`
    );
  }

  // 3. Confirm upload and trigger ingestion.
  const confirmRes = await apiFetch(`/api/projects/${projectId}/upload`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({documentId: document.id, filename: file.name}),
  });
  if (!confirmRes.ok) {
    throw new Error("Failed to trigger ingestion");
  }

  return {...document, status: "processing"} as ProjectDocument;
}

export async function deleteDocument(
  projectId: string,
  docId: string
): Promise<void> {
  const res = await apiFetch(`/api/projects/${projectId}/documents/${docId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete document");
}

export async function searchProjectDocuments(
  projectId: string,
  query: string,
  limit = 5
): Promise<ProjectSearchResult[]> {
  const res = await apiFetch(`/api/projects/${projectId}/search`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({query, limit}),
  });
  if (!res.ok) throw new Error("Failed to search project documents");
  const data = await res.json();
  return data.results ?? [];
}

export async function reingestDocument(
  projectId: string,
  docId: string,
  file: File
): Promise<ProjectDocument> {
  const initRes = await apiFetch(
    `/api/projects/${projectId}/documents/${docId}/reingest`,
    {
      method: "PATCH",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({filename: file.name, fileSize: file.size}),
    }
  );
  if (!initRes.ok) {
    const err = await initRes.json().catch(() => ({error: "Re-ingest failed"}));
    throw new Error(err.detail || err.error || "Re-ingest failed");
  }

  const {uploadUrl, ...document} = await initRes.json();

  const uploadRes = await fetch(uploadUrl, {
    method: "PUT",
    mode: "cors",
    body: file,
  });
  if (!uploadRes.ok) {
    const detail = await uploadRes.text().catch(() => "");
    throw new Error(
      `Direct upload to storage failed (${uploadRes.status}): ${detail.slice(
        0,
        300
      )}`
    );
  }

  const confirmRes = await apiFetch(`/api/projects/${projectId}/upload`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({documentId: document.id, filename: file.name}),
  });
  if (!confirmRes.ok) {
    throw new Error("Failed to trigger ingestion");
  }

  return {...document, status: "processing"} as ProjectDocument;
}

export async function pollDocumentStatus(
  projectId: string,
  docId: string
): Promise<{
  status: string;
  chunkCount: number;
  chunkStrategy: string | null;
  errorMessage: string | null;
}> {
  const res = await apiFetch(
    `/api/projects/${projectId}/documents/${docId}/status`
  );
  if (!res.ok) throw new Error("Failed to get document status");
  return res.json();
}

// ─── Project Chat ───

export async function fetchProjectSessions(
  projectId: string
): Promise<Session[]> {
  const res = await apiFetch(`/api/projects/${projectId}/sessions`);
  if (!res.ok) return [];
  return res.json();
}

export async function createProjectSession(
  projectId: string
): Promise<Session> {
  const res = await apiFetch(`/api/projects/${projectId}/session`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to create project session");
  return res.json();
}

export async function deleteProjectSession(
  projectId: string,
  sessionId: string
): Promise<void> {
  await apiFetch(`/api/projects/${projectId}/session/${sessionId}`, {
    method: "DELETE",
  });
}

export async function fetchAgents(): Promise<AgentInfo[]> {
  const res = await apiFetch("/api/projects/agents");
  if (!res.ok) return [];
  return res.json();
}

// ─── Memory API ───

export async function fetchMemory(): Promise<UserMemory> {
  const res = await apiFetch("/api/chat/memory");
  if (!res.ok) {
    return {facts: []};
  }
  return res.json();
}

export async function addMemoryFact(text: string): Promise<MemoryFact> {
  const res = await apiFetch("/api/chat/memory", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({text}),
  });
  if (!res.ok) {
    throw new Error("Failed to add memory");
  }
  return res.json();
}

export async function removeMemoryFact(factId: string): Promise<void> {
  const res = await apiFetch(`/api/chat/memory/${factId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error("Failed to remove memory");
  }
}

// ─── Project Chat Stream ───

export async function streamProjectChat(
  projectId: string,
  sessionId: string,
  message: string,
  onEvent: (event: SSEEvent) => void,
  agent?: string | null,
  signal?: AbortSignal
): Promise<void> {
  const res = await apiFetch(`/api/projects/${projectId}/chat`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({sessionId, message, agent: agent || null}),
    signal,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Project chat failed: ${res.status} ${text}`);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});

    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const lines = part.split("\n");
      let eventType = "";
      const dataLines: string[] = [];

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          dataLines.push(line.slice(6));
        }
      }

      const eventData = dataLines.join("\n");
      if (!eventType || dataLines.length === 0) continue;

      if (eventType === "token") {
        onEvent({type: "token", data: eventData});
      } else if (eventType === "agent") {
        try {
          onEvent({type: "agent", data: JSON.parse(eventData)});
        } catch {
          // ignore
        }
      } else if (eventType === "tool") {
        try {
          onEvent({type: "tool", data: JSON.parse(eventData)});
        } catch {
          // ignore
        }
      } else if (eventType === "tool_result") {
        try {
          onEvent({type: "tool_result", data: JSON.parse(eventData)});
        } catch {
          // ignore
        }
      } else if (eventType === "thinking") {
        try {
          onEvent({type: "thinking", data: JSON.parse(eventData)});
        } catch {
          // ignore
        }
      } else if (eventType === "retrieval") {
        try {
          onEvent({type: "retrieval", data: JSON.parse(eventData)});
        } catch {
          // ignore
        }
      } else if (eventType === "error") {
        onEvent({type: "error", data: eventData});
      } else if (eventType === "done") {
        try {
          onEvent({type: "done", data: JSON.parse(eventData)});
        } catch {
          onEvent({type: "done", data: {sources_used: 0, prompt_tokens: 0}});
        }
      }
    }
  }
}
