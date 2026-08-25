/**
 * Demo identities used to simulate role switching.
 *
 * These are a demonstration device only: the backend treats a client-supplied
 * actor/role as untrusted, and a real deployment must inject identity from a
 * trusted auth layer instead. See AGENTS.md, "Architecture & Safety".
 *
 * The Case workspace needs the two extra roles that only appear in the supply
 * expediting Path, so the overview and asset pages take a prefix of this list.
 */
import type { SidebarIdentity } from "../app-sidebar";

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

export const personAvatars: Record<string, string> = Object.fromEntries(
  demoIdentities.map((identity) => [identity.name, identity.avatarUrl]),
);

export const botAvatars = {
  orchestrator: "/avatars/bot-orchestrator.png",
  path: "/avatars/bot-path.png",
  synthesis: "/avatars/bot-synthesis.png",
} as const;
