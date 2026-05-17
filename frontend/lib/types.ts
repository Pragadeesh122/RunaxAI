export type MessageRole = 'user' | 'assistant';

export interface User {
  id: string;
  email: string;
  name: string | null;
  image: string | null;
}

export type ToolStatus = 'running' | 'done' | 'error';

export interface ToolCall {
  id: string;
  name: string;
  status: ToolStatus;
  args?: Record<string, unknown>;
  startedAt?: number;
  completedAt?: number;
  cacheHit?: boolean;
  backendId?: string;
}

export type ThinkingEntry =
  | { type: 'text'; content: string }
  | { type: 'tool'; toolCall: ToolCall };

export interface ChatAttachment {
  id: string;
  filename: string;
  mimeType: string;
  fileSize: number;
  storageKey: string;
}

export interface MessageMetadata {
  agentName?: string;
  quizState?: Record<number, { selected: string | null; revealed: boolean; shortAnswer: string }>;
  attachments?: ChatAttachment[];
}

export type AssistantMessageStatus =
  | { type: 'running' }
  | { type: 'requires-action'; reason: 'tool-calls' | 'interrupt' }
  | { type: 'complete'; reason: 'stop' | 'unknown' }
  | { type: 'incomplete'; reason: 'cancelled' | 'tool-calls' | 'length' | 'content-filter' | 'other' | 'error'; error?: unknown };

export type MessagePart =
  | { type: 'text'; text: string; parentId?: string }
  | { type: 'reasoning'; text: string; parentId?: string }
  | {
      type: 'tool-call';
      toolCallId: string;
      toolName: string;
      args: Record<string, unknown>;
      argsText: string;
      result?: unknown;
      isError?: boolean;
      parentId?: string;
    }
  | {
      type: 'source';
      sourceType: 'url';
      id: string;
      url: string;
      title?: string;
      parentId?: string;
    }
  | { type: 'data'; name: string; data: unknown };

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  parts: MessagePart[];
  toolCalls: ToolCall[];
  thinkingEntries: ThinkingEntry[];
  sources: RetrievalSource[];
  sourcesCached?: boolean;
  status?: AssistantMessageStatus;
  thinkingStartedAt?: number;
  thinkingDuration?: number;
  metadata: MessageMetadata;
  attachments?: ChatAttachment[];
  createdAt: string; // ISO string from DB
  agentName?: string; // set during streaming, persisted in metadata
  dbId?: string; // actual database id replaced after streaming completes
}

export interface Session {
  id: string;
  projectId?: string | null;
  backendSessionId: string | null;
  title: string;
  createdAt: string; // ISO string from DB
  updatedAt: string;
}

export interface ProjectDocument {
  id: string;
  filename: string;
  fileType: string;
  fileSize: number;
  chunkCount: number;
  chunkStrategy: string | null;
  status: 'uploading' | 'processing' | 'ready' | 'failed';
  errorMessage: string | null;
  createdAt: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  documents: ProjectDocument[];
  createdAt: string;
  updatedAt: string;
}

export interface ProjectSearchResult {
  id: string;
  snippet: string;
  source: string;
  page: number | null;
  score: number;
  documentId: string | null;
}

export interface RetrievalSource {
  source: string;
  page: number | null;
  score: number;
}

export interface AgentInfo {
  name: string;
  description: string;
  structured_output: boolean;
}

export interface MemoryFact {
  id: string;
  text: string;
  observed_at: string;
  source_session_id: string | null;
}

export interface UserMemory {
  facts: MemoryFact[];
}
