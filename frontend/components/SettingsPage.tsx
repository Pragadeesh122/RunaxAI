"use client";

import {useMemo, useState, type FormEvent} from "react";
import {ArrowLeft} from "@phosphor-icons/react/dist/ssr/ArrowLeft";
import {EnvelopeSimple} from "@phosphor-icons/react/dist/ssr/EnvelopeSimple";
import {Key} from "@phosphor-icons/react/dist/ssr/Key";
import {ShieldCheck} from "@phosphor-icons/react/dist/ssr/ShieldCheck";
import Link from "next/link";

import {changePassword, requestPasswordReset, signOut} from "@/lib/api";
import type {User} from "@/lib/types";

interface SettingsPageProps {
  user: User;
}

export default function SettingsPage({user}: SettingsPageProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changePasswordError, setChangePasswordError] = useState<string | null>(
    null
  );
  const [changePasswordSuccess, setChangePasswordSuccess] = useState<
    string | null
  >(null);
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const [resetEmail, setResetEmail] = useState(user.email);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetSuccess, setResetSuccess] = useState<string | null>(null);
  const [isRequestingReset, setIsRequestingReset] = useState(false);

  const displayName = useMemo(() => {
    if (user.name?.trim()) return user.name.trim();
    return user.email.split("@")[0];
  }, [user.email, user.name]);

  const handleChangePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setChangePasswordError(null);
    setChangePasswordSuccess(null);

    if (newPassword !== confirmPassword) {
      setChangePasswordError("Passwords do not match");
      return;
    }

    setIsChangingPassword(true);
    try {
      await changePassword(currentPassword, newPassword);
      setChangePasswordSuccess("Your password has been updated.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to change password";
      setChangePasswordError(message);
    } finally {
      setIsChangingPassword(false);
    }
  };

  const handlePasswordResetRequest = async (
    event: FormEvent<HTMLFormElement>
  ) => {
    event.preventDefault();
    setResetError(null);
    setResetSuccess(null);

    setIsRequestingReset(true);
    try {
      await requestPasswordReset(resetEmail.trim());
      setResetSuccess(
        "Reset instructions were requested. In local development, the backend logs the token."
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to request password reset";
      setResetError(message);
    } finally {
      setIsRequestingReset(false);
    }
  };

  return (
    <div className='relative min-h-screen overflow-hidden bg-black/90 text-zinc-100'>
      <div className='pointer-events-none absolute inset-0 ' />
      <div className='pointer-events-none absolute inset-0 opacity-[0.08] ' />

      <div className='relative z-10 mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 py-8'>
        <header className='flex items-center justify-between gap-4 border-b border-white/8 pb-5'>
          <div className='space-y-2'>
            <Link
              href='/chat'
              className='inline-flex items-center gap-2 text-sm text-zinc-400 transition-colors hover:text-zinc-100'>
              <ArrowLeft size={16} aria-hidden='true' />
              <span>Back to workspace</span>
            </Link>
            <div>
              <p className='text-xs uppercase tracking-[0.24em] text-emerald-400/70'>
                Settings
              </p>
              <h1 className='mt-2 text-3xl font-semibold tracking-tight text-zinc-100'>
                Account and security
              </h1>
              <p className='mt-2 max-w-2xl text-sm text-zinc-400'>
                Manage your credentials-based access, recovery flow, and account
                session controls from one place.
              </p>
            </div>
          </div>

          <button
            type='button'
            onClick={() => signOut()}
            className='rounded-xl border border-white/10 bg-white/4 px-4 py-2 text-sm font-medium text-zinc-200 transition-colors hover:bg-white/8'>
            Sign out
          </button>
        </header>

        <div className='mt-8 grid gap-6 lg:grid-cols-[1.1fr_0.9fr]'>
          <section className='space-y-6'>
            <div className='rounded-2xl border border-white/10 bg-[#1b1d21]/95 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.35)] backdrop-blur'>
              <div className='flex items-start gap-4'>
                <div className='flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] text-lg font-medium text-zinc-200'>
                  {(user.name?.charAt(0) || user.email.charAt(0)).toUpperCase()}
                </div>
                <div className='min-w-0'>
                  <p className='text-sm uppercase tracking-[0.22em] text-zinc-500'>
                    Account
                  </p>
                  <h2 className='mt-2 text-xl font-semibold text-zinc-100'>
                    {displayName}
                  </h2>
                  <p className='mt-1 text-sm text-zinc-400'>{user.email}</p>
                  <p className='mt-4 text-sm leading-6 text-zinc-400'>
                    FastAPI remains the auth authority for this workspace. This
                    page only manages the account controls that already exist on
                    the backend.
                  </p>
                </div>
              </div>
            </div>

            <div
              id='security'
              className='rounded-2xl border border-white/10 bg-[#1b1d21]/95 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.35)] backdrop-blur'>
              <div className='flex items-center gap-3'>
                <span className='rounded-xl border border-emerald-400/25 bg-emerald-500/12 p-2 text-emerald-300'>
                  <Key size={18} aria-hidden='true' />
                </span>
                <div>
                  <h2 className='text-lg font-semibold text-zinc-100'>
                    Change password
                  </h2>
                  <p className='text-sm text-zinc-400'>
                    Use this for credentials-based accounts. OAuth-only accounts
                    will be rejected by the backend.
                  </p>
                </div>
              </div>

              <form onSubmit={handleChangePassword} className='mt-5 space-y-4'>
                <div>
                  <label
                    htmlFor='current-password'
                    className='mb-1.5 block text-sm font-medium text-zinc-300'>
                    Current password
                  </label>
                  <input
                    id='current-password'
                    type='password'
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    autoComplete='current-password'
                    required
                    className='w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60'
                  />
                </div>

                <div className='grid gap-4 md:grid-cols-2'>
                  <div>
                    <label
                      htmlFor='new-password'
                      className='mb-1.5 block text-sm font-medium text-zinc-300'>
                      New password
                    </label>
                    <input
                      id='new-password'
                      type='password'
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                      autoComplete='new-password'
                      minLength={8}
                      required
                      className='w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60'
                    />
                  </div>

                  <div>
                    <label
                      htmlFor='confirm-password'
                      className='mb-1.5 block text-sm font-medium text-zinc-300'>
                      Confirm new password
                    </label>
                    <input
                      id='confirm-password'
                      type='password'
                      value={confirmPassword}
                      onChange={(event) =>
                        setConfirmPassword(event.target.value)
                      }
                      autoComplete='new-password'
                      minLength={8}
                      required
                      className='w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60'
                    />
                  </div>
                </div>

                {changePasswordError ? (
                  <p className='rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300'>
                    {changePasswordError}
                  </p>
                ) : null}

                {changePasswordSuccess ? (
                  <p className='rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200'>
                    {changePasswordSuccess}
                  </p>
                ) : null}

                <button
                  type='submit'
                  disabled={isChangingPassword}
                  className='rounded-xl border border-emerald-400/30 bg-emerald-500/15 px-4 py-2.5 text-sm font-medium text-emerald-100 transition-[transform,background-color,border-color,opacity] duration-150 hover:bg-emerald-500/22 active:scale-[0.96] active:-translate-y-[1px] disabled:opacity-50 disabled:active:scale-100 disabled:active:translate-y-0'>
                  {isChangingPassword ? "Please wait…" : "Change password"}
                </button>
              </form>
            </div>
          </section>

          <section className='space-y-6'>
            <div className='rounded-2xl border border-white/10 bg-[#1b1d21]/95 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.35)] backdrop-blur'>
              <div className='flex items-center gap-3'>
                <span className='rounded-xl border border-emerald-400/25 bg-emerald-500/12 p-2 text-emerald-300'>
                  <EnvelopeSimple size={18} aria-hidden='true' />
                </span>
                <div>
                  <h2 className='text-lg font-semibold text-zinc-100'>
                    Password recovery
                  </h2>
                  <p className='text-sm text-zinc-400'>
                    Use this if you do not know your current password and need
                    to restart access to the account.
                  </p>
                </div>
              </div>

              <form
                onSubmit={handlePasswordResetRequest}
                className='mt-5 space-y-4'>
                <div>
                  <label
                    htmlFor='reset-email'
                    className='mb-1.5 block text-sm font-medium text-zinc-300'>
                    Recovery email
                  </label>
                  <input
                    id='reset-email'
                    type='email'
                    value={resetEmail}
                    onChange={(event) => setResetEmail(event.target.value)}
                    autoComplete='email'
                    required
                    className='w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60'
                  />
                </div>

                {resetError ? (
                  <p className='rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300'>
                    {resetError}
                  </p>
                ) : null}

                {resetSuccess ? (
                  <p className='rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200'>
                    {resetSuccess}
                  </p>
                ) : null}

                <button
                  type='submit'
                  disabled={isRequestingReset}
                  className='w-full rounded-xl border border-emerald-400/30 bg-emerald-500/15 px-4 py-2.5 text-sm font-medium text-emerald-100 transition-[transform,background-color,border-color,opacity] duration-150 hover:bg-emerald-500/22 active:scale-[0.96] active:-translate-y-[1px] disabled:opacity-50 disabled:active:scale-100 disabled:active:translate-y-0'>
                  {isRequestingReset
                    ? "Please wait…"
                    : "Send reset instructions"}
                </button>
              </form>
            </div>

            <div className='rounded-2xl border border-white/10 bg-[#1b1d21]/95 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.35)] backdrop-blur'>
              <div className='flex items-center gap-3'>
                <span className='rounded-xl border border-emerald-400/20 bg-emerald-500/15 p-2 text-emerald-200'>
                  <ShieldCheck size={18} aria-hidden='true' />
                </span>
                <div>
                  <h2 className='text-lg font-semibold text-zinc-100'>
                    Session controls
                  </h2>
                  <p className='text-sm text-zinc-400'>
                    Leave the workspace cleanly from here or jump back to your
                    chat surface.
                  </p>
                </div>
              </div>

              <div className='mt-5 flex flex-col gap-3 sm:flex-row'>
                <Link
                  href='/chat'
                  className='inline-flex items-center justify-center rounded-xl border border-white/8 bg-white/3 px-4 py-2.5 text-sm font-medium text-zinc-200 transition-colors hover:bg-white/6'>
                  Return to chat
                </Link>
                <button
                  type='button'
                  onClick={() => signOut()}
                  className='inline-flex items-center justify-center rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-2.5 text-sm font-medium text-red-200 transition-colors hover:bg-red-500/15'>
                  Sign out of this browser
                </button>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
