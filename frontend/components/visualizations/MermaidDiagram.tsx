import { useEffect, useRef, useState } from "react";

interface MermaidDiagramProps {
  code: string;
  mermaidType?: string;
}

// ── Mermaid singleton: initialize once, render serially ──

let mermaidReady: Promise<typeof import("mermaid")["default"]> | null = null;
let renderQueue: Promise<void> = Promise.resolve();

function getMermaid() {
  if (!mermaidReady) {
    mermaidReady = import("mermaid").then((m) => {
      m.default.initialize({
        startOnLoad: false,
        theme: "base",
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
        fontSize: 14,
        securityLevel: "strict",

        themeVariables: {
          primaryColor: "#27272a",
          primaryTextColor: "#e4e4e7",
          primaryBorderColor: "#3f3f46",
          secondaryColor: "#27272a",
          secondaryTextColor: "#e4e4e7",
          secondaryBorderColor: "#3f3f46",
          tertiaryColor: "#27272a",
          tertiaryTextColor: "#e4e4e7",
          tertiaryBorderColor: "#3f3f46",
          lineColor: "#52525b",
          background: "transparent",
          mainBkg: "#27272a",
          nodeBorder: "#3f3f46",
          clusterBkg: "#1c1c1e",
          clusterBorder: "#3f3f46",
          titleColor: "#e4e4e7",
          edgeLabelBackground: "#18181b",
          nodeTextColor: "#e4e4e7",
          fontSize: "14px",
        },

        flowchart: {
          useMaxWidth: true,
          nodeSpacing: 50,
          rankSpacing: 40,
          padding: 10,
          diagramPadding: 15,
          wrappingWidth: 200,
          htmlLabels: true,
          curve: "basis",
        },
        mindmap: { useMaxWidth: true, padding: 10 },
        sequence: {
          useMaxWidth: true,
          actorFontSize: 13,
          messageFontSize: 13,
          noteFontSize: 11,
          actorMargin: 40,
          messageMargin: 30,
          mirrorActors: false,
        },
        gantt: { useMaxWidth: true },
      });
      return m.default;
    });
  }
  return mermaidReady;
}

/** Queue a mermaid render — only one runs at a time to avoid internal state corruption */
function queueRender(id: string, code: string): Promise<string> {
  const job = renderQueue.then(async () => {
    const mermaid = await getMermaid();
    try {
      const { svg } = await mermaid.render(id, code);
      return svg;
    } finally {
      // Clean up temp DOM elements mermaid creates
      document.getElementById(id)?.remove();
      document.getElementById(`d${id}`)?.remove();
    }
  });
  // Keep queue moving even if this job fails
  renderQueue = job.then(() => {}, () => {});
  return job;
}

// ── Sanitization ──

function fixMindmapIndentation(code: string): string {
  const lines = code.split("\n");
  if (!lines[0]?.trim().startsWith("mindmap")) return code;

  const rootIdx = lines.findIndex((l) => l.trim().startsWith("root"));
  if (rootIdx < 0) return code;

  const contentLines = lines.slice(rootIdx + 1);
  const nonEmpty = contentLines.filter((l) => l.trim());
  if (nonEmpty.length === 0) return code;

  const rootIndent = lines[rootIdx].search(/\S/);
  const allFlat = nonEmpty.every((l) => {
    const indent = l.search(/\S/);
    return indent >= 0 && indent <= rootIndent + 1;
  });
  if (!allFlat) return code;

  const items = nonEmpty.map((l) => l.trim());
  const CHILD = "    ";
  const GCHILD = "      ";

  const isCategory = items.map((text, i) => {
    if (text.split(/\s+/).length !== 1) return false;
    if (/\d/.test(text)) return false;
    const next = items[i + 1];
    return next !== undefined && next.split(/\s+/).length >= 2;
  });

  const result = [lines[0], `  root${lines[rootIdx].trim().replace(/^root/, "")}`];
  let inCategory = false;

  for (let i = 0; i < items.length; i++) {
    let text = items[i];
    if (/[/&'#;:%]/.test(text) && !text.startsWith('"')) {
      text = `"${text}"`;
    }
    if (isCategory[i]) {
      result.push(CHILD + text);
      inCategory = true;
    } else {
      result.push((inCategory ? GCHILD : CHILD) + text);
    }
  }

  return result.join("\n");
}

function sanitizeMermaidCode(code: string): string {
  let sanitized = code
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"');
  sanitized = fixMindmapIndentation(sanitized);
  return sanitized;
}

function cleanRenderedSvg(raw: string): string {
  // We want static SVGs that fit their container
  return raw.replace(/style="max-width:[^"]*"/, 'style="width:100%;height:auto;max-width:100%;"');
}

export default function MermaidDiagram({ code }: MermaidDiagramProps) {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const renderCount = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const sanitized = sanitizeMermaidCode(code);
    const renderId = `mermaid-${Date.now()}-${++renderCount.current}`;

    queueRender(renderId, sanitized)
      .then((rendered) => {
        if (!cancelled) {
          setSvg(cleanRenderedSvg(rendered));
          setError(null);
        }
      })
      .catch((e) => {
        console.error("[MermaidDiagram] render failed:", e);
        if (!cancelled) {
          setError(String(e));
          setSvg(null);
        }
      });

    return () => { cancelled = true; };
  }, [code]);

  if (error) {
    return (
      <pre className="text-xs text-zinc-500 bg-white/[0.02] rounded-lg p-3 overflow-x-auto whitespace-pre-wrap">
        {code}
      </pre>
    );
  }

  if (!svg) {
    return (
      <div className="flex items-center gap-2 py-3">
        <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
        <span className="text-sm text-zinc-400">Rendering diagram...</span>
      </div>
    );
  }

  return (
    <div className="my-8 flex justify-center bg-zinc-900/50 rounded-xl border border-white/5 p-6 overflow-hidden">
      <div 
        className="w-full max-w-full"
        dangerouslySetInnerHTML={{ __html: svg }} 
      />
    </div>
  );
}

