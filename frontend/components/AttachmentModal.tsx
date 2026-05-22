"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "@phosphor-icons/react/dist/ssr/X";
import { DownloadSimple } from "@phosphor-icons/react/dist/ssr/DownloadSimple";
import { FileText } from "@phosphor-icons/react/dist/ssr/FileText";
import { getChatAttachmentUrl } from "@/lib/api";
import type { ChatAttachment } from "@/lib/types";

interface AttachmentModalProps {
  attachment: ChatAttachment | null;
  onClose: () => void;
}

function isImageAttachment(att: ChatAttachment): boolean {
  if (att.mimeType.startsWith("image/")) return true;
  const ext = att.filename.includes(".")
    ? att.filename.split(".").pop()!.toLowerCase()
    : "";
  return ["png", "jpg", "jpeg", "webp", "gif"].includes(ext);
}

function isPdfAttachment(att: ChatAttachment): boolean {
  if (att.mimeType === "application/pdf") return true;
  return att.filename.toLowerCase().endsWith(".pdf");
}

export default function AttachmentModal({
  attachment,
  onClose,
}: AttachmentModalProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!attachment) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [attachment, onClose]);

  if (!attachment || !mounted) return null;

  const isImage = isImageAttachment(attachment);
  const isPdf = isPdfAttachment(attachment);
  const url = getChatAttachmentUrl(attachment);

  return createPortal(
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="relative flex flex-col w-full max-w-4xl max-h-[90vh] rounded-2xl bg-zinc-900 border border-white/10 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-white/8">
          <div className="flex items-center gap-2 min-w-0">
            <FileText size={18} className="text-zinc-400 shrink-0" aria-hidden="true" />
            <span className="text-sm font-medium text-zinc-100 truncate" title={attachment.filename}>
              {attachment.filename}
            </span>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <a
              href={url}
              download={attachment.filename}
              target="_blank"
              rel="noreferrer"
              aria-label="Download"
              className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-white/8 transition-colors"
            >
              <DownloadSimple size={18} aria-hidden="true" />
            </a>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-white/8 transition-colors"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        </header>

        <div className="flex-1 min-h-0 overflow-auto bg-black/30">
          {isImage ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={url}
              alt={attachment.filename}
              crossOrigin="use-credentials"
              className="block mx-auto max-h-[80vh]"
            />
          ) : isPdf ? (
            <iframe
              src={url}
              title={attachment.filename}
              className="w-full h-[80vh] border-0 bg-zinc-900"
            />
          ) : (
            <div className="flex flex-col items-center justify-center gap-3 h-64 px-6 text-center">
              <FileText size={28} className="text-zinc-500" aria-hidden="true" />
              <p className="text-sm text-zinc-400">
                Preview is not available for this file type.
              </p>
              <a
                href={url}
                download={attachment.filename}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-xs text-emerald-200 hover:bg-emerald-500/25 transition-colors"
              >
                <DownloadSimple size={14} aria-hidden="true" />
                Download
              </a>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
