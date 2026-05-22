"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import AuthSupportLayout from "@/components/AuthSupportLayout";
import { requestPasswordReset } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      await requestPasswordReset(email.trim());
      setSubmitted(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to request password reset";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthSupportLayout
      eyebrow="Recovery"
      title="Reset your password"
      description="Enter your account email and we’ll start the recovery flow for this account."
      sideTitle="Recover access without losing your workspace context."
      sideDescription="The recovery flow is only for cases where you no longer know the current password. If you are already signed in and know it, change it from settings instead."
      sidePoints={[
        "Use your account email to request recovery instructions.",
        "Password recovery does not change project or chat data.",
        "In local development, the backend logs the recovery link.",
      ]}
    >
      {submitted ? (
        <div className="space-y-3">
          <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            Recovery instructions were requested. In local development, the backend logs the
            recovery link.
          </p>
          <Link href="/auth/signin" className="text-sm text-emerald-300 hover:text-emerald-200">
            Back to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-zinc-300">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
              className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60"
              placeholder="you@example.com"
            />
          </div>

          {error ? (
            <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-xl border border-emerald-400/30 bg-emerald-500/18 px-4 py-2.5 text-sm font-medium text-emerald-100 transition-colors hover:bg-emerald-500/25 disabled:opacity-50"
          >
            {isSubmitting ? "Please wait..." : "Send reset instructions"}
          </button>

          <Link
            href="/auth/signin"
            className="block text-center text-sm text-zinc-400 hover:text-zinc-200"
          >
            Back to sign in
          </Link>
        </form>
      )}
    </AuthSupportLayout>
  );
}
