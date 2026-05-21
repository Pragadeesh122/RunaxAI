"use client";

import { useCallback, useState } from "react";
import type { MessageMetadata } from "@/lib/types";
import { updateMessageMetadata } from "@/lib/api";

interface QuizQuestion {
  id: number;
  type: "multiple_choice" | "true_false" | "short_answer";
  question: string;
  options?: string[];
  correct: string;
  explanation: string;
}

interface QuizData {
  title: string;
  questions: QuizQuestion[];
}

function tryParseQuiz(content: string): QuizData | null {
  const validate = (parsed: unknown): QuizData | null => {
    const p = parsed as QuizData;
    return p.title && Array.isArray(p.questions) ? p : null;
  };

  try { return validate(JSON.parse(content.trim())); } catch { /* not pure JSON */ }

  const fenceMatch = content.match(/```(?:json)?\s*\n?([\s\S]*?)\n?\s*```/);
  if (fenceMatch) {
    try { return validate(JSON.parse(fenceMatch[1].trim())); } catch { /* not valid JSON */ }
  }

  const braceStart = content.indexOf("{");
  if (braceStart >= 0) {
    let depth = 0;
    for (let i = braceStart; i < content.length; i++) {
      if (content[i] === "{") depth++;
      else if (content[i] === "}") depth--;
      if (depth === 0) {
        try { return validate(JSON.parse(content.slice(braceStart, i + 1))); } catch { /* not valid JSON */ }
        break;
      }
    }
  }

  return null;
}

interface QuestionState {
  selected: string | null;
  revealed: boolean;
  shortAnswer: string;
}

function QuestionCard({
  q,
  index,
  savedState,
  onStateChange,
}: {
  q: QuizQuestion;
  index: number;
  savedState?: QuestionState;
  onStateChange: (index: number, state: QuestionState) => void;
}) {
  const [selected, setSelected] = useState<string | null>(savedState?.selected ?? null);
  const [revealed, setRevealed] = useState(savedState?.revealed ?? false);
  const [shortAnswer, setShortAnswer] = useState(savedState?.shortAnswer ?? "");

  const persist = useCallback(
    (s: string | null, r: boolean, sa: string) => {
      onStateChange(index, { selected: s, revealed: r, shortAnswer: sa });
    },
    [index, onStateChange]
  );

  const isCorrect =
    q.type === "short_answer"
      ? shortAnswer.trim().toLowerCase() === q.correct.toLowerCase()
      : selected === q.correct;

  const handleSelect = (option: string) => {
    if (revealed) return;
    const value =
      q.type === "true_false" ? option : option.match(/^([A-Z])\)/)?.[1] ?? option;
    setSelected(value);
    persist(value, revealed, shortAnswer);
  };

  const handleReveal = () => {
    setRevealed(true);
    persist(selected, true, shortAnswer);
  };

  const handleShortAnswer = (value: string) => {
    setShortAnswer(value);
    persist(selected, revealed, value);
  };

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] overflow-hidden">
      <div className="px-4 py-3 border-b border-white/5 flex items-center gap-3">
        <span className="shrink-0 w-6 h-6 rounded-full bg-emerald-600/20 text-emerald-400 text-xs font-medium flex items-center justify-center">
          {index + 1}
        </span>
        <span className="text-sm font-medium text-zinc-200">{q.question}</span>
      </div>

      <div className="px-4 py-3 flex flex-col gap-2">
        {q.type === "short_answer" ? (
          <input
            type="text"
            value={shortAnswer}
            onChange={(e) => handleShortAnswer(e.target.value)}
            disabled={revealed}
            placeholder="Type your answer..."
            className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-zinc-200 placeholder:text-zinc-500 outline-none focus:border-emerald-500/50 disabled:opacity-50"
          />
        ) : (
          (q.options ?? []).map((opt) => {
            const optKey =
              q.type === "true_false"
                ? opt
                : opt.match(/^([A-Z])\)/)?.[1] ?? opt;
            const isSelected = selected === optKey;
            const isAnswer = optKey === q.correct;

            let style = "border-white/8 bg-white/[0.02] hover:bg-white/5";
            if (revealed && isAnswer) {
              style = "border-emerald-500/30 bg-emerald-500/10";
            } else if (revealed && isSelected && !isAnswer) {
              style = "border-red-500/30 bg-red-500/10";
            } else if (isSelected) {
              style = "border-emerald-500/30 bg-emerald-500/10";
            }

            return (
              <button
                key={opt}
                onClick={() => handleSelect(opt)}
                disabled={revealed}
                className={`text-left px-3 py-2 rounded-lg border text-sm text-zinc-300 transition-colors ${style} disabled:cursor-default`}
              >
                {opt}
              </button>
            );
          })
        )}
      </div>

      <div className="px-4 py-3 border-t border-white/5">
        {!revealed ? (
          <button
            onClick={handleReveal}
            disabled={q.type === "short_answer" ? !shortAnswer.trim() : !selected}
            className="text-xs font-medium text-emerald-400 hover:text-emerald-300 disabled:text-zinc-600 disabled:cursor-not-allowed transition-colors"
          >
            Reveal answer
          </button>
        ) : (
          <div className="flex flex-col gap-1.5">
            <span
              className={`text-xs font-medium ${isCorrect ? "text-emerald-400" : "text-red-400"}`}
            >
              {isCorrect ? "Correct!" : `Incorrect — answer: ${q.correct}`}
            </span>
            {q.explanation && (
              <p className="text-xs text-zinc-500 leading-relaxed">
                {q.explanation}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

interface QuizRendererProps {
  content: string;
  messageId: string;
  savedMetadata?: MessageMetadata;
}

export default function QuizRenderer({ content, messageId, savedMetadata }: QuizRendererProps) {
  const quiz = tryParseQuiz(content);
  const [quizState, setQuizState] = useState<Record<number, QuestionState>>(
    savedMetadata?.quizState ?? {}
  );

  const handleStateChange = useCallback(
    (index: number, state: QuestionState) => {
      setQuizState((prev) => {
        const next = { ...prev, [index]: state };
        // Persist to DB in the background
        updateMessageMetadata(messageId, { quizState: next }).catch(() => {
          /* silent — quiz still works locally */
        });
        return next;
      });
    },
    [messageId]
  );

  if (!quiz) return null;

  return (
    <div className="flex flex-col gap-3 w-full">
      <h3 className="text-base font-semibold text-zinc-100">{quiz.title}</h3>
      {quiz.questions.map((q, i) => (
        <QuestionCard
          key={q.id ?? i}
          q={q}
          index={i}
          savedState={quizState[i]}
          onStateChange={handleStateChange}
        />
      ))}
    </div>
  );
}

export { tryParseQuiz };
