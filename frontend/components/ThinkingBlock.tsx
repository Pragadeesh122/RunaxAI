'use client';

import { useState } from 'react';
import { CaretRight } from '@phosphor-icons/react/dist/ssr/CaretRight';
import { CircleNotch } from '@phosphor-icons/react/dist/ssr/CircleNotch';
import { CheckCircle } from '@phosphor-icons/react/dist/ssr/CheckCircle';
import { WarningCircle } from '@phosphor-icons/react/dist/ssr/WarningCircle';
import { Sparkle } from '@phosphor-icons/react/dist/ssr/Sparkle';
import type { ThinkingEntry } from '@/lib/types';

function formatToolName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

interface ThinkingBlockProps {
  entries: ThinkingEntry[];
  isStreaming: boolean;
  startedAt?: number;
  duration?: number;
}

export default function ThinkingBlock({
  entries,
  isStreaming,
  duration,
}: ThinkingBlockProps) {
  const [expandedOverride, setExpandedOverride] = useState<boolean | null>(null);
  const expanded = expandedOverride ?? duration === undefined;

  const formattedDuration = duration !== undefined ? duration.toFixed(1) : null;

  if (entries.length === 0 && !isStreaming) return null;

  return (
    <div className="w-full">
      {/* Header — clickable to expand/collapse */}
      <button
        onClick={() => setExpandedOverride((value) => !(value ?? duration === undefined))}
        className="flex items-center gap-1.5 group cursor-pointer py-1"
      >
        <CaretRight
          size={12}
          className={`text-zinc-500 transition-transform duration-200 ${
            expanded ? 'rotate-90' : ''
          }`}
        />
        {isStreaming ? (
          <>
            <Sparkle
              size={14}
              weight="fill"
              className="text-violet-400 animate-pulse"
            />
            <span className="text-xs text-zinc-400 font-medium">
              Thinking...
            </span>
          </>
        ) : (
          <span className="text-xs text-zinc-500 group-hover:text-zinc-400 transition-colors">
            {formattedDuration ? `Reasoned for ${formattedDuration}s` : 'Reasoned'}
          </span>
        )}
      </button>

      {/* Expandable content — unified timeline */}
      {expanded && entries.length > 0 && (
        <div className="mt-1 ml-[6px] pl-3 border-l-2 border-zinc-700/60 space-y-0.5 pb-1">
          {entries.map((entry, i) => {
            if (entry.type === 'text') {
              return (
                <p
                  key={i}
                  className="text-[12px] text-zinc-500 leading-relaxed"
                >
                  {entry.content}
                </p>
              );
            }

            const tool = entry.toolCall;
            return (
              <div key={tool.id} className="flex items-center gap-1.5 py-0.5">
                {tool.status === 'running' && (
                  <CircleNotch
                    size={13}
                    className="text-violet-400 animate-spin shrink-0"
                  />
                )}
                {tool.status === 'done' && (
                  <CheckCircle
                    size={13}
                    weight="duotone"
                    className="text-emerald-400 shrink-0"
                  />
                )}
                {tool.status === 'error' && (
                  <WarningCircle
                    size={13}
                    weight="duotone"
                    className="text-amber-400 shrink-0"
                  />
                )}
                <span
                  className={`text-[12px] font-medium ${
                    tool.status === 'running'
                      ? 'text-zinc-400'
                      : tool.status === 'done'
                      ? 'text-zinc-500'
                      : 'text-amber-400'
                  }`}
                >
                  {formatToolName(tool.name)}
                </span>
                {tool.status === 'running' && (
                  <span className="text-[11px] text-zinc-600">running...</span>
                )}
                {tool.cacheHit && tool.status === 'done' && (
                  <span
                    title="Served from cache"
                    className="inline-flex items-center gap-1 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300"
                  >
                    <span className="h-1 w-1 rounded-full bg-emerald-400" />
                    cached
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
