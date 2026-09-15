"use client";

/**
 * Demo identities used to simulate role switching.
 *
 * These are a demonstration device only: the backend treats a client-supplied
 * actor/role as untrusted, and a real deployment must inject identity from a
 * trusted auth layer instead. See AGENTS.md, "Architecture & Safety".
 *
 * The workbench shares one identity list and one selected identity across
 * routes so the sidebar, greeting, and Case permissions stay aligned.
 */
import { useCallback, useSyncExternalStore } from "react";

export type SidebarIdentity = {
  name: string;
  role: string;
  avatar: string;
  avatarUrl: string;
};

export const demoIdentities: SidebarIdentity[] = [
  { name: "陈澄", role: "订单统筹经理", avatar: "陈", avatarUrl: "/avatars/chen-cheng.png" },
  { name: "王淼", role: "主计划", avatar: "王", avatarUrl: "/avatars/wang-miao.png" },
  { name: "林乔", role: "研发", avatar: "林", avatarUrl: "/avatars/lin-qiao.png" },
  { name: "赵宁", role: "供应经理", avatar: "赵", avatarUrl: "/avatars/zhao-ning.png" },
  { name: "周岚", role: "采购与供应协同", avatar: "周", avatarUrl: "/avatars/zhou-lan.png" },
  { name: "吴桐", role: "物流", avatar: "吴", avatarUrl: "/avatars/wu-tong.png" },
];

/** The four roles that appear in the material substitution Golden Path. */
export const coreDemoIdentities: SidebarIdentity[] = demoIdentities.slice(0, 4);

const STORAGE_KEY = "agentic-cm.demo-identity";
const DEFAULT_IDENTITY_NAME = demoIdentities[0].name;
const listeners = new Set<() => void>();
let currentIdentityName = DEFAULT_IDENTITY_NAME;

export const personAvatars: Record<string, string> = Object.fromEntries(
  demoIdentities.map((identity) => [identity.name, identity.avatarUrl]),
);

export const botAvatars = {
  orchestrator: "/avatars/bot-orchestrator-transparent.png",
  path: "/avatars/bot-path-transparent.png",
  synthesis: "/avatars/bot-synthesis-transparent.png",
} as const;

export function resolveDemoIdentity(name: string | null | undefined): SidebarIdentity {
  return demoIdentities.find((identity) => identity.name === name) ?? demoIdentities[0];
}

function readStoredIdentityName(): string {
  try {
    return resolveDemoIdentity(window.localStorage.getItem(STORAGE_KEY)).name;
  } catch {
    return DEFAULT_IDENTITY_NAME;
  }
}

if (typeof window !== "undefined") {
  currentIdentityName = readStoredIdentityName();
}

function emitIdentityChange() {
  for (const listener of listeners) listener();
}

function subscribeDemoIdentity(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setDemoIdentity(name: string) {
  const nextName = resolveDemoIdentity(name).name;
  if (nextName === currentIdentityName) return;
  currentIdentityName = nextName;
  try {
    window.localStorage.setItem(STORAGE_KEY, nextName);
  } catch {
    // Demo identity persistence is best-effort.
  }
  emitIdentityChange();
}

export function useDemoIdentity() {
  const name = useSyncExternalStore(
    subscribeDemoIdentity,
    () => currentIdentityName,
    () => DEFAULT_IDENTITY_NAME,
  );
  const identity = resolveDemoIdentity(name);
  const selectIdentity = useCallback((next: SidebarIdentity) => {
    setDemoIdentity(next.name);
  }, []);
  return { identity, identities: demoIdentities, selectIdentity };
}
