"use client";

import {forwardRef, type ButtonHTMLAttributes} from "react";

type Variant = "primary" | "secondary" | "ghost" | "destructive";

interface TactileButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  fullWidth?: boolean;
}

const VARIANT_CLASSES: Record<Variant, string> = {
  primary:
    "bg-emerald-500/18 border border-emerald-400/30 text-emerald-100 hover:bg-emerald-500/25 hover:border-emerald-400/45 disabled:opacity-50",
  secondary:
    "bg-white/[0.04] border border-white/10 text-zinc-200 hover:bg-white/[0.07] hover:border-white/15 disabled:opacity-50",
  ghost:
    "bg-transparent border border-transparent text-zinc-300 hover:bg-white/[0.04] hover:text-zinc-100 disabled:opacity-50",
  destructive:
    "bg-rose-500/12 border border-rose-500/30 text-rose-200 hover:bg-rose-500/20 hover:border-rose-500/45 disabled:opacity-50",
};

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium " +
  "transition-[transform,background-color,border-color,opacity] duration-150 " +
  "active:scale-[0.96] active:-translate-y-[1px] " +
  "disabled:cursor-not-allowed disabled:active:scale-100 disabled:active:translate-y-0 " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/40";

const TactileButton = forwardRef<HTMLButtonElement, TactileButtonProps>(
  ({variant = "primary", fullWidth, className = "", children, ...rest}, ref) => {
    return (
      <button
        ref={ref}
        className={`${BASE} ${VARIANT_CLASSES[variant]} ${fullWidth ? "w-full" : ""} ${className}`}
        {...rest}
      >
        {children}
      </button>
    );
  }
);

TactileButton.displayName = "TactileButton";

export default TactileButton;
