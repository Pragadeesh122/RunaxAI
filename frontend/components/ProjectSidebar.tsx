'use client';

import { useRef, useState } from 'react';
import { PencilSimpleLineIcon } from '@phosphor-icons/react/dist/ssr/PencilSimpleLine';
import { TrashIcon } from '@phosphor-icons/react/dist/ssr/Trash';
import { FileArrowUp } from '@phosphor-icons/react/dist/ssr/FileArrowUp';
import { File as FileIcon } from '@phosphor-icons/react/dist/ssr/File';
import { FilePdf } from '@phosphor-icons/react/dist/ssr/FilePdf';
import { FileCsv } from '@phosphor-icons/react/dist/ssr/FileCsv';
import { FileDoc } from '@phosphor-icons/react/dist/ssr/FileDoc';
import { FileText } from '@phosphor-icons/react/dist/ssr/FileText';
import { ArrowClockwise } from '@phosphor-icons/react/dist/ssr/ArrowClockwise';
import { SpinnerGap } from '@phosphor-icons/react/dist/ssr/SpinnerGap';
import { CheckCircle } from '@phosphor-icons/react/dist/ssr/CheckCircle';
import { XCircle } from '@phosphor-icons/react/dist/ssr/XCircle';
import { Brain } from '@phosphor-icons/react/dist/ssr/Brain';
import { Exam } from '@phosphor-icons/react/dist/ssr/Exam';
import { ChartBar } from '@phosphor-icons/react/dist/ssr/ChartBar';
import { ListBullets } from '@phosphor-icons/react/dist/ssr/ListBullets';
import { Lightning } from '@phosphor-icons/react/dist/ssr/Lightning';
import { ChatTeardropDots } from '@phosphor-icons/react/dist/ssr/ChatTeardropDots';
import { MagnifyingGlass } from '@phosphor-icons/react/dist/ssr/MagnifyingGlass';
import { X } from '@phosphor-icons/react/dist/ssr/X';
import { RunaxLogo } from './ChatArea';
import SidebarAccountFooter from './SidebarAccountFooter';
import type { Project, AgentInfo, Session, ProjectSearchResult, User } from '@/lib/types';

const AGENT_ICONS: Record<string, React.ReactNode> = {
  reasoning: <Brain size={16} className="text-violet-400" />,
  quiz: <Exam size={16} className="text-blue-400" />,
  visualization: <ChartBar size={16} className="text-emerald-400" />,
  summary: <ListBullets size={16} className="text-amber-400" />,
};

function FileTypeIcon({ type }: { type: string }) {
  const size = 16;
  switch (type) {
    case 'pdf':
      return <FilePdf size={size} className="text-red-400" />;
    case 'csv':
      return <FileCsv size={size} className="text-green-400" />;
    case 'docx':
      return <FileDoc size={size} className="text-blue-400" />;
    case 'txt':
    case 'md':
      return <FileText size={size} className="text-zinc-400" />;
    default:
      return <FileIcon size={size} className="text-zinc-400" />;
  }
}

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'processing':
    case 'uploading':
      return <SpinnerGap size={14} className="text-amber-400 animate-spin" />;
    case 'ready':
      return <CheckCircle size={14} className="text-emerald-400" />;
    case 'failed':
      return <XCircle size={14} className="text-red-400" />;
    default:
      return null;
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface ProjectSidebarProps {
  project: Project;
  agents: AgentInfo[];
  selectedAgent: string | null;
  onSelectAgent: (name: string | null) => void;
  onUploadFile: (file: File) => void;
  onReingestDocument: (docId: string, file: File) => void;
  onDeleteDocument: (docId: string) => void;
  isUploading: boolean;
  reingestingDocumentId: string | null;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  onSearch: () => void;
  onClearSearch: () => void;
  searchResults: ProjectSearchResult[];
  isSearching: boolean;
  sessions: Session[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  user: Pick<User, 'name' | 'email' | 'image'>;
  onSignOut: () => void;
}

export default function ProjectSidebar({
  project,
  agents,
  selectedAgent,
  onSelectAgent,
  onUploadFile,
  onReingestDocument,
  onDeleteDocument,
  isUploading,
  reingestingDocumentId,
  searchQuery,
  onSearchQueryChange,
  onSearch,
  onClearSearch,
  searchResults,
  isSearching,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  user,
  onSignOut,
}: ProjectSidebarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const replaceFileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [replaceTargetId, setReplaceTargetId] = useState<string | null>(null);
  const [expandedResultId, setExpandedResultId] = useState<string | null>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) onUploadFile(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onUploadFile(file);
    e.target.value = '';
  };

  const handleReplaceFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && replaceTargetId) {
      onReingestDocument(replaceTargetId, file);
    }
    e.target.value = '';
    setReplaceTargetId(null);
  };

  const readyDocs = project.documents.filter((d) => d.status === 'ready');
  const totalChunks = readyDocs.reduce((sum, d) => sum + d.chunkCount, 0);

  return (
    <aside className="flex flex-col h-full bg-[#1e1e1e] border-r border-white/6">
      {/* Header */}
      <div className="px-4 py-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-linear-to-br from-violet-600/30 to-purple-600/30 border border-violet-500/20 flex items-center justify-center shrink-0">
              <RunaxLogo size={22} />
            </div>
            <span className="text-sm font-semibold text-zinc-200 tracking-tight truncate">
              {project.name}
            </span>
          </div>
          <button
            onClick={onNewChat}
            aria-label="New chat"
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100 shrink-0"
          >
            <PencilSimpleLineIcon size={17} aria-hidden="true" />
          </button>
        </div>
        {project.description && (
          <p className="text-xs text-zinc-500 mt-1 line-clamp-2">{project.description}</p>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {/* Chat sessions */}
        <div className="mb-3">
          <p className="px-3 mb-1 text-[11px] font-medium uppercase tracking-widest text-zinc-500 select-none">
            Chats
          </p>
          {sessions.length === 0 ? (
            <div className="flex flex-col items-center gap-1.5 px-3 py-4 text-center select-none">
              <ChatTeardropDots size={20} className="text-zinc-700" aria-hidden="true" />
              <p className="text-xs text-zinc-600">No conversations yet</p>
            </div>
          ) : (
            <ul role="list" className="flex flex-col gap-0.5">
              {sessions.map((s) => (
                <li key={s.id} className="group relative">
                  <button
                    onClick={() => onSelectSession(s.id)}
                    className={`
                      w-full text-left px-3 py-2 rounded-lg text-sm truncate transition-colors duration-150
                      ${activeSessionId === s.id
                        ? 'bg-violet-500/20 text-zinc-100'
                        : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
                      }
                    `}
                    aria-current={activeSessionId === s.id ? 'true' : undefined}
                  >
                    {s.title || 'New chat'}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(s.id);
                    }}
                    aria-label={`Delete chat: ${s.title || 'New chat'}`}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-400 hover:bg-white/5 transition-all duration-150 focus:opacity-100"
                  >
                    <TrashIcon size={13} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="border-t border-white/6 mb-3" />

        {/* Agent selector */}
        <div className="mb-3">
          <p className="px-3 mb-1.5 text-[11px] font-medium uppercase tracking-widest text-zinc-500 select-none">
            Agent
          </p>
          <div className="flex flex-col gap-0.5">
            <button
              onClick={() => onSelectAgent(null)}
              className={`flex items-center gap-2 px-2.5 py-2 rounded-lg text-sm transition-colors duration-150 ${
                selectedAgent === null
                  ? 'bg-violet-500/20 text-zinc-100'
                  : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
              }`}
            >
              <Lightning size={16} className="text-violet-400" />
              <span>Auto</span>
            </button>
            {agents.map((agent) => (
              <button
                key={agent.name}
                onClick={() => onSelectAgent(agent.name)}
                className={`flex items-center gap-2 px-2.5 py-2 rounded-lg text-sm transition-colors duration-150 ${
                  selectedAgent === agent.name
                    ? 'bg-violet-500/20 text-zinc-100'
                    : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
                }`}
              >
                {AGENT_ICONS[agent.name] || <Brain size={16} className="text-zinc-400" />}
                <span className="capitalize">{agent.name}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="border-t border-white/6 mb-3" />

        {/* Search */}
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1.5">
            <p className="px-1 text-[11px] font-medium uppercase tracking-widest text-zinc-500 select-none">
              Search
            </p>
            {searchResults.length > 0 && (
              <button
                onClick={onClearSearch}
                className="p-1 rounded text-zinc-600 hover:text-zinc-300 transition-colors duration-100"
                aria-label="Clear search"
              >
                <X size={12} />
              </button>
            )}
          </div>

          <div className="flex items-center gap-1.5 px-2 py-2 rounded-xl border border-white/10 bg-white/3">
            <MagnifyingGlass size={15} className="text-zinc-500 shrink-0" />
            <input
              value={searchQuery}
              onChange={(e) => onSearchQueryChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSearch();
                if (e.key === 'Escape') onClearSearch();
              }}
              placeholder="Search documents…"
              className="flex-1 bg-transparent text-sm text-zinc-200 placeholder-zinc-600 outline-none"
            />
            <button
              onClick={onSearch}
              disabled={isSearching || !searchQuery.trim()}
              className="px-2 py-1 text-[11px] rounded-md bg-violet-500/15 text-violet-300 border border-violet-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSearching ? '...' : 'Go'}
            </button>
          </div>

          {searchResults.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1">
              {searchResults.map((result) => {
                const isExpanded = expandedResultId === result.id;
                return (
                  <li
                    key={result.id}
                    className="rounded-lg border border-white/8 bg-white/3"
                  >
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedResultId(isExpanded ? null : result.id)
                      }
                      className="w-full text-left px-2.5 py-2 rounded-lg hover:bg-white/5 transition-colors duration-100"
                      aria-expanded={isExpanded}
                    >
                      <p className="text-xs font-medium text-zinc-300 truncate">
                        {result.source}
                      </p>
                      {!isExpanded && (
                        <p className="mt-1 text-[11px] text-zinc-500 line-clamp-3">
                          {result.snippet}
                        </p>
                      )}
                      <p className="mt-1 text-[10px] text-zinc-600">
                        {result.page !== null ? `Page ${result.page} · ` : ''}
                        Score {result.score.toFixed(2)}
                        <span className="ml-1 text-zinc-700">
                          {isExpanded ? '· hide' : '· show chunk'}
                        </span>
                      </p>
                    </button>
                    {isExpanded && (
                      <div className="px-2.5 pb-2.5 -mt-1">
                        <p className="text-[11px] leading-relaxed text-zinc-400 whitespace-pre-wrap break-words max-h-72 overflow-y-auto rounded-md border border-white/5 bg-black/20 p-2">
                          {result.text || result.snippet}
                        </p>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="border-t border-white/6 mb-3" />

        {/* Documents */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <p className="px-1 text-[11px] font-medium uppercase tracking-widest text-zinc-500 select-none">
              Documents
            </p>
            <span className="text-[11px] text-zinc-600">
              {readyDocs.length} file{readyDocs.length !== 1 ? 's' : ''} &middot; {totalChunks} chunks
            </span>
          </div>

          {/* Upload area */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`flex flex-col items-center gap-1.5 px-3 py-4 mb-2 rounded-xl border border-dashed cursor-pointer transition-all duration-150 ${
              isDragOver
                ? 'border-violet-500/50 bg-violet-500/10'
                : 'border-white/10 hover:border-white/20 hover:bg-white/3'
            } ${isUploading ? 'pointer-events-none opacity-60' : ''}`}
          >
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileChange}
              accept=".pdf,.txt,.md,.csv,.docx"
              className="hidden"
            />
            <input
              ref={replaceFileInputRef}
              type="file"
              onChange={handleReplaceFileChange}
              accept=".pdf,.txt,.md,.csv,.docx"
              className="hidden"
            />
            {isUploading ? (
              <SpinnerGap size={20} className="text-violet-400 animate-spin" />
            ) : (
              <FileArrowUp size={20} className="text-zinc-500" />
            )}
            <span className="text-xs text-zinc-500">
              {isUploading ? 'Uploading...' : 'Drop files or click to upload'}
            </span>
            <span className="text-[10px] text-zinc-600">PDF, TXT, MD, CSV, DOCX</span>
          </div>

          {/* Document list */}
          <ul className="flex flex-col gap-0.5">
            {project.documents.map((doc) => (
              <li key={doc.id} className="group relative">
                <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-white/3 transition-colors duration-150">
                  <FileTypeIcon type={doc.fileType} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-zinc-300 truncate">{doc.filename}</p>
                    <p className="text-[11px] text-zinc-600">
                      {formatFileSize(doc.fileSize)}
                      {doc.status === 'ready' && ` \u00B7 ${doc.chunkCount} chunks`}
                    </p>
                  </div>
                  <StatusBadge status={doc.status} />
                  <button
                    onClick={() => {
                      setReplaceTargetId(doc.id);
                      replaceFileInputRef.current?.click();
                    }}
                    disabled={isUploading || reingestingDocumentId === doc.id}
                    aria-label={`Replace ${doc.filename}`}
                    className="p-1 rounded opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-violet-300 transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {reingestingDocumentId === doc.id ? (
                      <SpinnerGap size={13} className="animate-spin" />
                    ) : (
                      <ArrowClockwise size={13} />
                    )}
                  </button>
                  <button
                    onClick={() => onDeleteDocument(doc.id)}
                    aria-label={`Delete ${doc.filename}`}
                    className="p-1 rounded opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-400 transition-all duration-150"
                  >
                    <TrashIcon size={13} />
                  </button>
                </div>
              </li>
            ))}
          </ul>

          {project.documents.length === 0 && (
            <div className="flex flex-col items-center gap-1.5 py-6 text-center">
              <FileIcon size={20} className="text-zinc-700" />
              <p className="text-xs text-zinc-600">No documents yet</p>
            </div>
          )}
        </div>
      </nav>
      <SidebarAccountFooter user={user} onSignOut={onSignOut} />
    </aside>
  );
}
