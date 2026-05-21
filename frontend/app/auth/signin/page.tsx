"use client";

import {useEffect, useState, type FormEvent} from "react";
import {ShieldCheck} from "@phosphor-icons/react/dist/ssr/ShieldCheck";
import {Database} from "@phosphor-icons/react/dist/ssr/Database";
import {Lightning} from "@phosphor-icons/react/dist/ssr/Lightning";
import {
  apiFetch,
  loginWithCredentials,
  registerWithCredentials,
} from "@/lib/api";
import {useAuth} from "@/components/AuthProvider";
import {useRouter} from "next/navigation";
import Link from "next/link";

function GoogleBrandIcon({size = 18}: {size?: number}) {
  return (
    <svg width={size} height={size} viewBox='0 0 18 18' aria-hidden='true'>
      <path
        fill='#EA4335'
        d='M17.64 9.2045c0-.6382-.0573-1.2518-.1636-1.8409H9v3.4818h4.8436c-.2086 1.125-.8432 2.0782-1.7977 2.715v2.2582h2.9086c1.7023-1.5668 2.6855-3.8755 2.6855-6.6141z'
      />
      <path
        fill='#4285F4'
        d='M9 18c2.43 0 4.4673-.8059 5.9564-2.1818l-2.9086-2.2582c-.8059.54-1.8368.8591-3.0477.8591-2.3441 0-4.3282-1.5832-5.0368-3.7105H.9573v2.3318C2.4382 15.9827 5.4818 18 9 18z'
      />
      <path
        fill='#FBBC05'
        d='M3.9632 10.7086A5.4095 5.4095 0 013.6818 9c0-.5927.1014-1.1686.2814-1.7086V4.9595H.9573A8.9968 8.9968 0 000 9c0 1.4523.3477 2.8277.9573 4.0405l3.0059-2.3319z'
      />
      <path
        fill='#34A853'
        d='M9 3.5795c1.3214 0 2.5077.4541 3.4405 1.345L15.0218 2.3432C13.4632.8905 11.4259 0 9 0 5.4818 0 2.4382 2.0173.9573 4.9595l3.0059 2.3319C4.6718 5.1627 6.6559 3.5795 9 3.5795z'
      />
    </svg>
  );
}

export default function SignIn() {
  const {user, isLoading} = useAuth();
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);
  const [authMode, setAuthMode] = useState<"signin" | "register">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user && !isLoading) {
      router.replace("/chat");
    }
  }, [user, isLoading, router]);

  const handleGoogleLogin = async () => {
    setIsGoogleLoading(true);
    setError(null);
    try {
      const res = await apiFetch("/auth/google/authorize");
      if (res.ok) {
        const data = await res.json();
        // Force account picker so users can switch accounts after logout.
        const url = new URL(data.authorization_url);
        url.searchParams.set("prompt", "select_account");
        window.location.href = url.toString();
      } else {
        console.error("Failed to get Google authorization URL");
        setError("Failed to start Google authentication");
        setIsGoogleLoading(false);
      }
    } catch (err) {
      console.error(err);
      setError("Google authentication failed");
      setIsGoogleLoading(false);
    }
  };

  const handleCredentialsAuth = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      if (authMode === "register") {
        await registerWithCredentials(email.trim(), password);
      }

      await loginWithCredentials(email.trim(), password);
      // Full page navigation ensures the server-side auth check on /chat
      // sees the newly-set cookie (SPA navigation via router can race it).
      window.location.href = "/chat";
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Authentication failed";
      setError(message);
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className='relative flex h-screen w-screen flex-col items-center justify-center overflow-hidden bg-black/90 text-zinc-200'>
        <div className='relative z-10 flex flex-col items-center gap-3 rounded-2xl border border-white/10 bg-[#1b1d21]/90 px-8 py-7 backdrop-blur'>
          <div className='h-9 w-9 rounded-full border-2 border-zinc-700 border-t-emerald-400 animate-spin' />
          <p className='text-sm text-zinc-300'>
            Loading authentication state...
          </p>
        </div>
      </div>
    );
  }

  if (user) return null;

  return (
    <div className='relative min-h-screen overflow-hidden bg-black/90 text-zinc-100'>
      <div className='relative z-10 mx-auto flex min-h-screen w-full max-w-6xl items-center px-6 py-10'>
        <div className='hidden flex-1 pr-12 lg:block'>
          <p className='mb-3 text-xs uppercase tracking-[0.24em] text-emerald-300/80'>
            RunaxAI
          </p>
          <h1 className='max-w-xl text-4xl font-semibold leading-tight tracking-tight text-zinc-100'>
            Secure access to your retrieval and agent workflows.
          </h1>
          <p className='mt-5 max-w-lg text-base leading-relaxed text-zinc-400'>
            Sign in to continue with chat orchestration, project knowledge
            bases, and tool execution across database, web, and document
            pipelines.
          </p>
          <div className='mt-8 space-y-3'>
            <div className='flex items-center gap-3 text-sm text-zinc-300'>
              <span className='rounded-md border border-emerald-500/30 bg-emerald-500/10 p-1.5'>
                <ShieldCheck size={16} className='text-emerald-300' />
              </span>
              Session cookies are HTTP-only and scoped to backend auth.
            </div>
            <div className='flex items-center gap-3 text-sm text-zinc-300'>
              <span className='rounded-md border border-emerald-500/30 bg-emerald-500/10 p-1.5'>
                <Database size={16} className='text-emerald-300' />
              </span>
              Chat history and projects stay isolated per account.
            </div>
            <div className='flex items-center gap-3 text-sm text-zinc-300'>
              <span className='rounded-md border border-emerald-500/30 bg-emerald-500/10 p-1.5'>
                <Lightning size={16} className='text-emerald-300' />
              </span>
              Continue directly into the `/chat` workspace after auth.
            </div>
          </div>
        </div>

        <div className='w-full max-w-md rounded-2xl border border-white/10 bg-[#1b1d21]/95 p-7 shadow-[0_24px_80px_rgba(0,0,0,0.45)] backdrop-blur'>
          <h2 className='text-2xl font-semibold tracking-tight text-zinc-100'>
            {authMode === "signin" ? "Welcome back" : "Create your account"}
          </h2>
          <p className='mt-1 text-sm text-zinc-400'>
            {authMode === "signin"
              ? "Sign in to continue to your workspace."
              : "Register, then continue directly to your workspace."}
          </p>

          <div className='mt-5 grid grid-cols-2 rounded-xl border border-white/10 bg-black/20 p-1'>
            <button
              type='button'
              onClick={() => {
                setAuthMode("signin");
                setError(null);
              }}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                authMode === "signin"
                  ? "bg-emerald-500/20 text-emerald-200 border border-emerald-400/30"
                  : "text-zinc-400 hover:text-zinc-100"
              }`}>
              Sign in
            </button>
            <button
              type='button'
              onClick={() => {
                setAuthMode("register");
                setError(null);
              }}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                authMode === "register"
                  ? "bg-emerald-500/20 text-emerald-200 border border-emerald-400/30"
                  : "text-zinc-400 hover:text-zinc-100"
              }`}>
              Create account
            </button>
          </div>

          <form onSubmit={handleCredentialsAuth} className='mt-5 space-y-4'>
            <div>
              <label
                htmlFor='email'
                className='mb-1.5 block text-sm font-medium text-zinc-300'>
                Email
              </label>
              <input
                id='email'
                type='email'
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete='email'
                required
                className='w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60'
                placeholder='you@example.com'
              />
            </div>

            <div>
              <label
                htmlFor='password'
                className='mb-1.5 block text-sm font-medium text-zinc-300'>
                Password
              </label>
              <input
                id='password'
                type='password'
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={
                  authMode === "signin" ? "current-password" : "new-password"
                }
                required
                minLength={8}
                className='w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-sm text-zinc-100 outline-none transition-colors placeholder:text-zinc-500 focus:border-emerald-400/60'
                placeholder='At least 8 characters'
              />
              <div className='mt-2 text-right'>
                <Link
                  href='/auth/forgot-password'
                  className='text-xs text-emerald-300/80 hover:text-emerald-200'>
                  Forgot password?
                </Link>
              </div>
            </div>

            {error ? (
              <p className='rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300'>
                {error}
              </p>
            ) : null}

            <button
              type='submit'
              disabled={isSubmitting || isGoogleLoading}
              className='w-full rounded-xl border border-emerald-400/30 bg-emerald-500/18 px-4 py-2.5 text-sm font-medium text-emerald-100 transition-colors hover:bg-emerald-500/25 disabled:opacity-50'>
              {isSubmitting
                ? "Please wait..."
                : authMode === "signin"
                ? "Sign in with email"
                : "Create account"}
            </button>
          </form>

          <div className='my-6 flex items-center gap-3'>
            <div className='h-px flex-1 bg-white/10' />
            <span className='text-xs uppercase tracking-[0.18em] text-zinc-500'>
              or
            </span>
            <div className='h-px flex-1 bg-white/10' />
          </div>

          <button
            onClick={handleGoogleLogin}
            disabled={isGoogleLoading || isSubmitting}
            className='flex w-full items-center justify-center gap-3 rounded-xl border border-white/12 bg-white/6 px-4 py-2.5 text-sm font-medium text-zinc-100 transition-colors hover:bg-white/10 disabled:opacity-50'>
            {isGoogleLoading ? (
              <div className='h-5 w-5 rounded-full border-2 border-zinc-500 border-t-zinc-100 animate-spin' />
            ) : (
              <>
                <GoogleBrandIcon size={19} />
                Continue with Google
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
