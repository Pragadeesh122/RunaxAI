'use client';

import { useState, useCallback } from 'react';
import { PencilSimpleLineIcon } from '@phosphor-icons/react/dist/ssr/PencilSimpleLine';
import { TrashIcon } from '@phosphor-icons/react/dist/ssr/Trash';
import { ChatTeardropDots } from '@phosphor-icons/react/dist/ssr/ChatTeardropDots';
import { FolderSimple } from '@phosphor-icons/react/dist/ssr/FolderSimple';
import { Plus } from '@phosphor-icons/react/dist/ssr/Plus';
import { RunaxLogo } from './ChatArea';
import SidebarAccountFooter from './SidebarAccountFooter';
import { createProject, deleteProject } from '@/lib/api';
import type { Session, Project, User } from '@/lib/types';

function parseSessionTime(value: string): number {
  if (!value) return 0;
  // Backend emits naive UTC strings (no timezone suffix). Normalize to UTC.
  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/.test(value);
  const normalized = hasTimezone ? value : `${value}Z`;
  const ts = Date.parse(normalized);
  return Number.isNaN(ts) ? 0 : ts;
}

function groupSessionsByTime(
  sessions: Session[],
  referenceTime: string
): {
  today: Session[];
  yesterday: Session[];
  older: Session[];
} {
  const oneDayMs = 24 * 60 * 60 * 1000;
  const referenceTs = parseSessionTime(referenceTime);
  const startOfToday = new Date(referenceTs || Date.now());
  startOfToday.setUTCHours(0, 0, 0, 0);
  const startOfYesterday = new Date(startOfToday.getTime() - oneDayMs);

  const today: Session[] = [];
  const yesterday: Session[] = [];
  const older: Session[] = [];

  const sorted = [...sessions].sort(
    (a, b) => parseSessionTime(b.updatedAt) - parseSessionTime(a.updatedAt)
  );

  for (const s of sorted) {
    const ts = parseSessionTime(s.updatedAt);
    if (ts >= startOfToday.getTime()) {
      today.push(s);
    } else if (ts >= startOfYesterday.getTime()) {
      yesterday.push(s);
    } else {
      older.push(s);
    }
  }

  return { today, yesterday, older };
}

interface SidebarProps {
  sessions: Session[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  initialProjects?: Project[];
  referenceTime: string;
  user: Pick<User, 'name' | 'email' | 'image'>;
  onSignOut: () => void;
}

interface SessionGroupProps {
  label: string;
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

function SessionGroup({ label, sessions, activeSessionId, onSelect, onDelete }: SessionGroupProps) {
  if (sessions.length === 0) return null;
  return (
    <div className="mb-4">
      <p className="px-3 mb-1 text-[11px] font-medium uppercase tracking-widest text-zinc-500 select-none">
        {label}
      </p>
      <ul role="list" className="flex flex-col gap-0.5">
        {sessions.map((s) => (
          <li key={s.id} className="group relative">
            <button
              onClick={() => onSelect(s.id)}
              className={`
                w-full text-left px-3 py-2.5 rounded-lg text-sm truncate transition-colors duration-150
                ${activeSessionId === s.id
                  ? 'bg-emerald-500/15 text-zinc-100 border-l-2 border-emerald-400'
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
                onDelete(s.id);
              }}
              aria-label={`Delete session: ${s.title || 'New chat'}`}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-400 hover:bg-white/5 transition-colors duration-150 focus:opacity-100"
            >
              <TrashIcon size={14} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  initialProjects = [],
  referenceTime,
  user,
  onSignOut,
}: SidebarProps) {
  const { today, yesterday, older } = groupSessionsByTime(
    sessions,
    referenceTime
  );
  const [projects, setProjects] = useState<Project[]>(initialProjects);
  const [showNewProject, setShowNewProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');

  const handleCreateProject = useCallback(async () => {
    const name = newProjectName.trim();
    if (!name) return;
    try {
      const project = await createProject(name);
      setProjects((prev) => [project, ...prev]);
      setNewProjectName('');
      setShowNewProject(false);
      // Navigate to the new project
      window.location.href = `/projects/${project.id}`;
    } catch (err) {
      console.error('Failed to create project:', err);
    }
  }, [newProjectName]);

  const handleDeleteProject = useCallback(async (id: string) => {
    try {
      await deleteProject(id);
      setProjects((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      console.error('Failed to delete project:', err);
    }
  }, []);

  return (
    <aside
      className="flex flex-col h-full bg-[#1e1e1e] border-r border-white/6"
      aria-label="Chat sessions"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-4 shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-linear-to-br from-emerald-500/20 to-emerald-400/10 border border-emerald-400/25 flex items-center justify-center shrink-0">
            <RunaxLogo size={22} />
          </div>
          <span className="text-sm font-semibold text-zinc-200 tracking-tight">RunaxAI</span>
        </div>

        <button
          onClick={onNewChat}
          aria-label="New chat"
          className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-white/8 transition-colors duration-100"
        >
          <PencilSimpleLineIcon size={17} aria-hidden="true" />
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        {/* Projects section */}
        <div className="mb-4">
          <div className="flex items-center justify-between px-3 mb-1">
            <p className="text-[11px] font-medium uppercase tracking-widest text-zinc-500 select-none">
              Projects
            </p>
            <button
              onClick={() => setShowNewProject((v) => !v)}
              aria-label="New project"
              className="p-0.5 rounded text-zinc-500 hover:text-zinc-300 transition-colors duration-100"
            >
              <Plus size={14} aria-hidden="true" />
            </button>
          </div>

          {showNewProject && (
            <div className="px-2 mb-1.5">
              <input
                autoFocus
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreateProject();
                  if (e.key === 'Escape') {
                    setShowNewProject(false);
                    setNewProjectName('');
                  }
                }}
                placeholder="Project name..."
                className="w-full px-2.5 py-1.5 text-sm bg-white/5 border border-white/10 rounded-lg text-zinc-200 placeholder-zinc-600 outline-none focus:border-emerald-400/40"
              />
            </div>
          )}

          <ul className="flex flex-col gap-0.5">
            {projects.map((p) => (
              <li key={p.id} className="group relative">
                <a
                  href={`/projects/${p.id}`}
                  className="flex items-center gap-2 w-full text-left px-3 py-2.5 rounded-lg text-sm text-zinc-400 hover:bg-white/5 hover:text-zinc-200 transition-colors duration-150"
                >
                  <FolderSimple size={16} className="text-emerald-400/70 shrink-0" aria-hidden="true" />
                  <span className="truncate">{p.name}</span>
                  <span className="ml-auto text-[11px] text-zinc-600 shrink-0">
                    {p.documents.length}
                  </span>
                </a>
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleDeleteProject(p.id);
                  }}
                  aria-label={`Delete project: ${p.name}`}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-400 hover:bg-white/5 transition-all duration-150 focus:opacity-100"
                >
                  <TrashIcon size={13} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>

          {projects.length === 0 && !showNewProject && (
            <p className="px-3 text-xs text-zinc-600">No projects yet</p>
          )}
        </div>

        <div className="border-t border-white/6 mb-4" />

        {/* Chat sessions */}
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-3 py-8 text-center select-none">
            <ChatTeardropDots size={24} className="text-zinc-700" aria-hidden="true" />
            <p className="text-xs text-zinc-600">No conversations yet</p>
          </div>
        ) : (
          <>
            <SessionGroup
              label="Today"
              sessions={today}
              activeSessionId={activeSessionId}
              onSelect={onSelectSession}
              onDelete={onDeleteSession}
            />
            <SessionGroup
              label="Yesterday"
              sessions={yesterday}
              activeSessionId={activeSessionId}
              onSelect={onSelectSession}
              onDelete={onDeleteSession}
            />
            <SessionGroup
              label="Older"
              sessions={older}
              activeSessionId={activeSessionId}
              onSelect={onSelectSession}
              onDelete={onDeleteSession}
            />
          </>
        )}
      </nav>
      <SidebarAccountFooter user={user} onSignOut={onSignOut} />
    </aside>
  );
}
