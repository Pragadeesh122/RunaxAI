"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { GearSix } from "@phosphor-icons/react/dist/ssr/GearSix";
import { SignOut } from "@phosphor-icons/react/dist/ssr/SignOut";

import type { User } from "@/lib/types";

interface SidebarAccountFooterProps {
  user: Pick<User, "name" | "email" | "image">;
  onSignOut: () => void;
}

function getDisplayName(user: Pick<User, "name" | "email" | "image">): string {
  if (user.name?.trim()) return user.name.trim();
  return user.email.split("@")[0];
}

function getInitial(user: Pick<User, "name" | "email" | "image">): string {
  const source = user.name?.trim() || user.email;
  return source.charAt(0).toUpperCase();
}

export default function SidebarAccountFooter({
  user,
  onSignOut,
}: SidebarAccountFooterProps) {
  const pathname = usePathname();
  const isSettingsPage = pathname === "/settings";

  return (
    <div className="shrink-0 border-t border-white/6 px-3 py-3">
      <div className="flex items-center gap-3 px-1 pb-3">
        {user.image ? (
          <Image
            src={user.image}
            alt={getDisplayName(user)}
            width={36}
            height={36}
            referrerPolicy="no-referrer"
            className="h-9 w-9 rounded-full border border-white/10 object-cover"
          />
        ) : (
          <div className="flex h-9 w-9 items-center justify-center rounded-full border border-emerald-400/20 bg-emerald-500/15 text-sm font-medium text-emerald-200">
            {getInitial(user)}
          </div>
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-zinc-200">{getDisplayName(user)}</p>
          <p className="truncate text-xs text-zinc-500">{user.email}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Link
          href="/settings"
          aria-current={isSettingsPage ? "page" : undefined}
          className={`flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm transition-colors ${
            isSettingsPage
              ? "border-emerald-400/30 bg-emerald-500/18 text-emerald-100"
              : "border-white/8 bg-white/3 text-zinc-300 hover:bg-white/6 hover:text-zinc-100"
          }`}
        >
          <GearSix size={15} aria-hidden="true" />
          <span>Settings</span>
        </Link>
        <button
          type="button"
          onClick={onSignOut}
          className="flex items-center justify-center gap-2 rounded-xl border border-white/8 bg-white/3 px-3 py-2 text-sm text-zinc-300 transition-colors hover:bg-white/6 hover:text-zinc-100"
        >
          <SignOut size={15} aria-hidden="true" />
          <span>Sign out</span>
        </button>
      </div>
    </div>
  );
}
