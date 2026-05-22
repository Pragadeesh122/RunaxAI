"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import AuthSupportLayout from "@/components/AuthSupportLayout";
import { resetPassword } from "@/lib/api";

export default function ResetPasswordPage() {
  const searchParams = useSearchParams();
  const [token, setToken] = useState(searchParams.get("token") ?? "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const hasPrefilledToken = token.trim().length > 0;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setIsSubmitting(true);
    try {
      await resetPassword(token.trim(), password);
      setSubmitted(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to reset password";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthSupportLayout
      eyebrow="Reset"
      title="Set a new password"
      description={
        hasPrefilledToken
          ? "Choose a new password for this account."
          : "Finish the recovery flow by providing the recovery code and a new password."
      }
      sideTitle="Finish recovery and get back into your workspace."
      sideDescription="This page is the final step in the recovery flow. Most users will arrive here from the recovery link automatically, so the code is usually already attached."
      sidePoints={[
        "Create a new password with at least 8 characters.",
        "Your projects and chat sessions remain tied to the same account.",
        "If you opened this directly in local development, paste the recovery code from the backend log.",
      ]}
    >
      {submitted ? (
        <div className="space-y-3">
          <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            Your password has been updated.
          </p>
          <Link href="/auth/signin" className="text-sm text-emerald-300 hover:text-emerald-200">
            Continue to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {!hasPrefilledToken ? (
            <div>
              <label htmlFor="token" className="mb-1.5 block text-sm font-medium text-zinc-300">
                Recovery code
              </label>
              <input
                id="token"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                required
                className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60"
                placeholder="Paste recovery code"
              />
            </div>
          ) : (
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/8 px-3 py-2 text-sm text-emerald-200">
              Recovery link confirmed. Choose your new password below.
            </div>
          )}

          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-zinc-300">
              New password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={8}
              required
              className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60"
              placeholder="At least 8 characters"
            />
          </div>

          <div>
            <label
              htmlFor="confirm-password"
              className="mb-1.5 block text-sm font-medium text-zinc-300"
            >
              Confirm new password
            </label>
            <input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              minLength={8}
              required
              className="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60"
              placeholder="Repeat new password"
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
            {isSubmitting ? "Please wait..." : "Update password"}
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
