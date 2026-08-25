"use client";

import Link from "next/link";
import Image from "next/image";
import { useState } from "react";

export type SidebarIdentity = { name: string; role: string; avatar: string; avatarUrl: string };

type AppSidebarProps = {
  active: "overview" | "workspace" | "inbox" | "activity" | "skills" | "policies" | "knowledge";
  identity: SidebarIdentity;
  identities: SidebarIdentity[];
  inboxCount?: number;
  busy?: boolean;
  onInboxOpen?: () => void;
  onIdentitySelect?: (index: number) => void;
};

export default function AppSidebar({
  active,
  identity,
  identities,
  inboxCount = 3,
  busy = false,
  onInboxOpen,
  onIdentitySelect,
}: AppSidebarProps) {
  const [showIdentityMenu, setShowIdentityMenu] = useState(false);

  function selectIdentity(index: number) {
    onIdentitySelect?.(index);
    setShowIdentityMenu(false);
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brandMark">AC</span>
        <span><strong>Agentic CM</strong><small>Case Management</small></span>
      </div>

      <nav className="primaryNav" aria-label="主导航">
        <p>工作区</p>
        <Link className={`navLink ${active === "overview" ? "active" : ""}`} href="/"><span className="navIcon">⌂</span>Case 总览</Link>
        <Link className={`navLink ${active === "workspace" ? "active" : ""}`} href="/cases/CM-2026-014"><span className="navIcon">◇</span>Case 工作台</Link>
        {onInboxOpen ? (
          <button className={`navLink ${active === "inbox" ? "active" : ""}`} type="button" onClick={onInboxOpen} style={{width:"100%",border:0,textAlign:"left"}}>
            <span className="navIcon">✓</span>我的待办<b>{inboxCount}</b>
          </button>
        ) : (
          <Link className={`navLink ${active === "inbox" ? "active" : ""}`} href="/cases/CM-2026-014#inbox"><span className="navIcon">✓</span>我的待办<b>{inboxCount}</b></Link>
        )}
        <a className={`navLink ${active === "activity" ? "active" : ""}`} href="#activity"><span className="navIcon">↗</span>协作动态</a>

        <p>组织资产</p>
        <Link className={`navLink ${active === "skills" ? "active" : ""}`} href="/assets/skills"><span className="navIcon">✦</span>Skills</Link>
        <Link className={`navLink ${active === "policies" ? "active" : ""}`} href="/assets/policies"><span className="navIcon">⌘</span>Policies</Link>
        <Link className={`navLink ${active === "knowledge" ? "active" : ""}`} href="/assets/knowledge"><span className="navIcon">◫</span>Knowledge</Link>
        <a className="navLink" href="#audit"><span className="navIcon">≡</span>审计记录</a>
      </nav>

      <div className="sidebarFoot">
        <div className="systemStatus"><i/>系统运行正常 <span>v0.1</span></div>
        <button className="identityButton" type="button" disabled={busy} onClick={() => setShowIdentityMenu((value) => !value)} aria-expanded={showIdentityMenu}>
          <span className="avatar"><Image src={identity.avatarUrl} alt="" width={64} height={64} /></span>
          <span><strong>{identity.name}</strong><small>{identity.role}</small></span>
          <b>⌄</b>
        </button>
        {showIdentityMenu && (
          <div className="identityMenu">
            <small>Demo identity simulation</small>
            {identities.map((item, index) => (
              <button type="button" key={`${item.name}-${item.role}`} onClick={() => selectIdentity(index)} aria-current={item.name === identity.name ? "true" : undefined}>
                <span className="avatar"><Image src={item.avatarUrl} alt="" width={64} height={64} /></span>
                <span>{item.name}<small>{item.role}</small></span>
              </button>
            ))}
            <p>仅模拟查看权限，不连接或修改 ERP</p>
          </div>
        )}
      </div>
    </aside>
  );
}
