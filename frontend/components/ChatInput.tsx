'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent } from 'react';
import { PaperPlaneTilt } from '@phosphor-icons/react/dist/ssr/PaperPlaneTilt';
import { Stop } from '@phosphor-icons/react/dist/ssr/Stop';
import { Paperclip } from '@phosphor-icons/react/dist/ssr/Paperclip';
import { X } from '@phosphor-icons/react/dist/ssr/X';
import { FileText } from '@phosphor-icons/react/dist/ssr/FileText';
import {
  CHAT_ATTACHMENT_MAX_BYTES,
  CHAT_ATTACHMENT_MAX_COUNT,
  CHAT_SESSION_MAX_BYTES,
  CHAT_SESSION_MAX_FILES,
  isAllowedChatAttachment,
  uploadChatAttachment,
} from '@/lib/api';
import type { ChatAttachment } from '@/lib/types';

interface PendingUpload {
  localId: string;
  file: File;
  previewUrl: string | null;
  error?: string;
}

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  isStreaming: boolean;
  disabled: boolean;
  placeholder?: string;
  attachments?: ChatAttachment[];
  onAttachmentsChange?: (next: ChatAttachment[]) => void;
  sessionFileCount?: number;
  sessionBytes?: number;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function isImage(mime: string, name: string): boolean {
  if (mime.startsWith('image/')) return true;
  const ext = name.includes('.') ? name.split('.').pop()!.toLowerCase() : '';
  return ['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext);
}

export default function ChatInput({
  value,
  onChange,
  onSubmit,
  onStop,
  isStreaming,
  disabled,
  placeholder = 'Send a message...',
  attachments,
  onAttachmentsChange,
  sessionFileCount = 0,
  sessionBytes = 0,
}: ChatInputProps) {
  const attachmentsEnabled = !!onAttachmentsChange;
  const currentAttachments = attachments ?? [];
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const lineHeight = 24;
    const maxLines = 6;
    const maxHeight = lineHeight * maxLines + 24;
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
  }, [value]);

  // Revoke object URLs when uploads finish/cleanup.
  useEffect(() => {
    return () => {
      pendingUploads.forEach((p) => {
        if (p.previewUrl) URL.revokeObjectURL(p.previewUrl);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totalCount = currentAttachments.length + pendingUploads.length;
  const canSubmit =
    value.trim().length > 0 && !disabled && pendingUploads.length === 0;

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (canSubmit) onSubmit();
    }
  };

  const flashError = useCallback((msg: string) => {
    setErrorMessage(msg);
    window.setTimeout(() => setErrorMessage(null), 4000);
  }, []);

  const startUpload = useCallback(
    async (file: File) => {
      const localId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const previewUrl = isImage(file.type, file.name)
        ? URL.createObjectURL(file)
        : null;
      const entry: PendingUpload = { localId, file, previewUrl };
      setPendingUploads((prev) => [...prev, entry]);

      try {
        const attachment = await uploadChatAttachment(file);
        onAttachmentsChange?.([...currentAttachments, attachment]);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Upload failed';
        flashError(`${file.name}: ${msg}`);
      } finally {
        setPendingUploads((prev) => {
          const found = prev.find((p) => p.localId === localId);
          if (found?.previewUrl) URL.revokeObjectURL(found.previewUrl);
          return prev.filter((p) => p.localId !== localId);
        });
      }
    },
    [currentAttachments, onAttachmentsChange, flashError]
  );

  const stagedBytes = useMemo(
    () => currentAttachments.reduce((sum, a) => sum + (a.fileSize || 0), 0),
    [currentAttachments]
  );
  const usedFileCount = sessionFileCount + totalCount;
  const usedBytes = sessionBytes + stagedBytes;
  const sessionLimitsReached =
    usedFileCount >= CHAT_SESSION_MAX_FILES ||
    usedBytes >= CHAT_SESSION_MAX_BYTES;

  const acceptFiles = useCallback(
    (files: FileList | File[]) => {
      const incoming = Array.from(files);
      if (incoming.length === 0) return;

      const turnSlots = CHAT_ATTACHMENT_MAX_COUNT - totalCount;
      const sessionSlots = CHAT_SESSION_MAX_FILES - (sessionFileCount + totalCount);
      const remainingSlots = Math.max(0, Math.min(turnSlots, sessionSlots));
      if (remainingSlots <= 0) {
        if (turnSlots <= 0) {
          flashError(`Max ${CHAT_ATTACHMENT_MAX_COUNT} files per message`);
        } else {
          flashError(`Session limit: ${CHAT_SESSION_MAX_FILES} files total`);
        }
        return;
      }

      let bytesBudget = CHAT_SESSION_MAX_BYTES - usedBytes;
      const accepted: File[] = [];
      for (const file of incoming.slice(0, remainingSlots)) {
        if (!isAllowedChatAttachment(file)) {
          flashError(`${file.name}: unsupported file type`);
          continue;
        }
        if (file.size > CHAT_ATTACHMENT_MAX_BYTES) {
          flashError(
            `${file.name}: exceeds ${CHAT_ATTACHMENT_MAX_BYTES / (1024 * 1024)} MB limit`
          );
          continue;
        }
        if (file.size > bytesBudget) {
          flashError(
            `${file.name}: would exceed session limit of ${CHAT_SESSION_MAX_BYTES / (1024 * 1024)} MB`
          );
          continue;
        }
        bytesBudget -= file.size;
        accepted.push(file);
      }
      if (incoming.length > remainingSlots) {
        flashError(`Only ${remainingSlots} more file(s) allowed`);
      }
      accepted.forEach((file) => {
        void startUpload(file);
      });
    },
    [totalCount, sessionFileCount, usedBytes, startUpload, flashError]
  );

  const handleFilePickerChange: React.ChangeEventHandler<HTMLInputElement> = (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    acceptFiles(files);
    e.target.value = ''; // allow re-picking the same file
  };

  const handleRemoveAttachment = (id: string) => {
    onAttachmentsChange?.(currentAttachments.filter((a) => a.id !== id));
  };

  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    if (!attachmentsEnabled) return;
    if (!e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    dragCounterRef.current += 1;
    setIsDragging(true);
  };
  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    if (!attachmentsEnabled) return;
    if (!e.dataTransfer.types.includes('Files')) return;
    dragCounterRef.current -= 1;
    if (dragCounterRef.current <= 0) {
      dragCounterRef.current = 0;
      setIsDragging(false);
    }
  };
  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (!attachmentsEnabled) return;
    if (!e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  };
  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    if (!attachmentsEnabled) return;
    if (!e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    dragCounterRef.current = 0;
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) {
      acceptFiles(e.dataTransfer.files);
    }
  };

  const acceptAttr = useMemo(
    () =>
      [
        'image/png',
        'image/jpeg',
        'image/webp',
        'image/gif',
        '.png',
        '.jpg',
        '.jpeg',
        '.webp',
        '.gif',
        '.pdf',
        '.txt',
        '.md',
        '.csv',
        '.docx',
        'application/pdf',
        'text/plain',
        'text/markdown',
        'text/csv',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      ].join(','),
    []
  );

  const showChipRow =
    attachmentsEnabled &&
    (currentAttachments.length > 0 || pendingUploads.length > 0);

  return (
    <div className="flex flex-col gap-0">
      <div
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className={`
          relative flex flex-col gap-2 w-full rounded-2xl border px-4 py-3
          bg-white/5
          transition-colors duration-200
          ${isDragging
            ? 'border-emerald-400/60 bg-emerald-500/5'
            : isStreaming || disabled
              ? 'border-white/8'
              : 'border-white/10 focus-within:border-emerald-400/40'
          }
        `}
      >
        {isDragging && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-emerald-500/5 border border-dashed border-emerald-400/40 pointer-events-none">
            <span className="text-xs text-emerald-300">Drop to attach</span>
          </div>
        )}

        {showChipRow && (
          <div className="flex flex-wrap gap-2">
            {currentAttachments.map((att) => (
              <div
                key={att.id}
                className="group flex items-center gap-2 pl-1.5 pr-1 py-1 rounded-lg bg-white/5 border border-white/10 text-xs"
              >
                <span className="flex items-center justify-center w-6 h-6 rounded bg-white/5 text-zinc-400">
                  <FileText size={14} aria-hidden="true" />
                </span>
                <span className="max-w-[180px] truncate text-zinc-200" title={att.filename}>
                  {att.filename}
                </span>
                <span className="text-zinc-500 text-[10px]">
                  {formatBytes(att.fileSize)}
                </span>
                <button
                  type="button"
                  onClick={() => handleRemoveAttachment(att.id)}
                  aria-label={`Remove ${att.filename}`}
                  className="ml-0.5 p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-white/10 transition-colors"
                >
                  <X size={12} weight="bold" aria-hidden="true" />
                </button>
              </div>
            ))}
            {pendingUploads.map((up) => (
              <div
                key={up.localId}
                className="relative overflow-hidden flex items-center gap-2 pl-1.5 pr-2.5 py-1 rounded-lg bg-white/5 border border-white/10 text-xs"
              >
                <span className="flex items-center justify-center w-6 h-6 rounded bg-white/5 text-zinc-400">
                  <FileText size={14} aria-hidden="true" />
                </span>
                <span className="max-w-[180px] truncate text-zinc-300" title={up.file.name}>
                  {up.file.name}
                </span>
                <span className="text-zinc-500 text-[10px]">
                  {formatBytes(up.file.size)}
                </span>
                {/* Skeleton shimmer — replaces circular spinner (skill §3 R5 + §8) */}
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0 left-0 w-1/3 bg-linear-to-r from-transparent via-white/10 to-transparent animate-skeleton pointer-events-none"
                />
              </div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2">
          {attachmentsEnabled && (
            <>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={totalCount >= CHAT_ATTACHMENT_MAX_COUNT || sessionLimitsReached || isStreaming}
                aria-label="Attach files"
                className="shrink-0 mb-0.5 p-1 rounded-md text-zinc-500 hover:text-zinc-200 hover:bg-white/8 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <Paperclip size={18} aria-hidden="true" />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={acceptAttr}
                onChange={handleFilePickerChange}
                className="hidden"
              />
            </>
          )}

          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled && !isStreaming}
            placeholder={placeholder}
            rows={1}
            aria-label="Message input"
            aria-multiline="true"
            className="flex-1 bg-transparent text-sm text-zinc-100 placeholder-zinc-600 resize-none outline-none leading-6 min-h-6 overflow-y-auto disabled:cursor-not-allowed disabled:text-zinc-500"
          />

          <div className="shrink-0 mb-0.5">
            {isStreaming ? (
              <button
                onClick={onStop}
                aria-label="Stop generation"
                className="flex items-center justify-center w-8 h-8 rounded-full bg-zinc-700 hover:bg-zinc-600 border border-white/10 text-zinc-300 hover:text-white transition-all duration-150"
              >
                <Stop size={14} weight="fill" aria-hidden="true" />
              </button>
            ) : (
              <button
                onClick={() => canSubmit && onSubmit()}
                disabled={!canSubmit}
                aria-label="Send message"
                className={`transition-[transform,color] duration-150 active:scale-[0.92] ${
                  canSubmit
                    ? 'text-emerald-400 hover:text-emerald-300'
                    : 'text-zinc-700 cursor-not-allowed'
                }`}
              >
                <PaperPlaneTilt size={20} weight="fill" aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </div>

      {errorMessage && (
        <p className="text-center text-[11px] text-rose-400/90 mt-1.5 select-none">
          {errorMessage}
        </p>
      )}
      {!errorMessage && attachmentsEnabled && usedFileCount > 0 && (
        <p className="text-center text-[11px] text-zinc-700 mt-1.5 select-none">
          {usedFileCount}/{CHAT_SESSION_MAX_FILES} files &middot;{' '}
          {formatBytes(usedBytes)}/{CHAT_SESSION_MAX_BYTES / (1024 * 1024)} MB this session
        </p>
      )}
      {!errorMessage && (!attachmentsEnabled || usedFileCount === 0) && (
        <p className="text-center text-[11px] text-zinc-700 mt-1.5 select-none">
          Enter to send &middot; Shift+Enter for new line &middot; <kbd className="text-zinc-600">/</kbd> to focus
        </p>
      )}
    </div>
  );
}
