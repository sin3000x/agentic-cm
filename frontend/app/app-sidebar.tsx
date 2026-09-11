"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";
import { useDemoIdentity, type SidebarIdentity } from "./lib/identities";

import { apiGet, apiPost } from "./lib/api";

type Adapter = "deterministic" | "openai-compatible";

export type { SidebarIdentity };

type AppSidebarProps = {
  active: "none" | "overview" | "inbox" | "skills" | "policies" | "knowledge";
  inboxCount?: number;
  busy?: boolean;
  onIdentitySelect?: (identity: SidebarIdentity) => void;
};

export default function AppSidebar({
  active,
  inboxCount,
  busy = false,
  onIdentitySelect,
}: AppSidebarProps) {
  const { identity, identities, selectIdentity: setIdentity } = useDemoIdentity();
  const [showIdentityMenu, setShowIdentityMenu] = useState(false);

  const [adapter, setAdapter] = useState<Adapter | "">("");
  const [savingAdapter, setSavingAdapter] = useState(false);
  const [adapterError, setAdapterError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiGet<{ adapter: Adapter }>("/api/runtime-config")
      .then((config) => { if (!cancelled) setAdapter(config.adapter); })
      .catch(() => { if (!cancelled) setAdapterError("无法读取运行模式，请刷新重试"); });
    return () => { cancelled = true; };
  }, []);

  async function selectAdapter(value: Adapter) {
    setSavingAdapter(true);
    setAdapterError("");
    try {
      const config = await apiPost<{ adapter: Adapter }>("/api/runtime-config", { adapter: value });
      setAdapter(config.adapter);
    } catch (error) {
      setAdapterError(error instanceof Error ? error.message : "切换失败，请重试");
    } finally {
      setSavingAdapter(false);
    }
  }

  function selectIdentity(item: SidebarIdentity) {
    setIdentity(item);
    onIdentitySelect?.(item);
    setShowIdentityMenu(false);
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brandMark">AC</span>
        <span>
          <strong>Agentic CM</strong>
          <small>Case Management</small>
        </span>
      </div>

      <nav className="primaryNav" aria-label="主导航">
        <p>工作区</p>
        <Link className={`navLink ${active === "overview" ? "active" : ""}`} href="/">
          <span className="navIcon">⌂</span>Case 总览
        </Link>
        <Link className={`navLink ${active === "inbox" ? "active" : ""}`} href="/inbox">
          <span className="navIcon">✓</span>我的待办
          {inboxCount !== undefined && <b>{inboxCount}</b>}
        </Link>

        <p>组织资产</p>
        <Link className={`navLink ${active === "skills" ? "active" : ""}`} href="/assets/skills">
          <span className="navIcon">✦</span>Skills
        </Link>
        <Link
          className={`navLink ${active === "policies" ? "active" : ""}`}
          href="/assets/policies"
        >
          <span className="navIcon">⌘</span>Policies
        </Link>
        <Link
          className={`navLink ${active === "knowledge" ? "active" : ""}`}
          href="/assets/knowledge"
        >
          <span className="navIcon">◫</span>Knowledge
        </Link>
        <a className="navLink" href="#audit">
          <span className="navIcon">≡</span>审计记录
        </a>
      </nav>

      <div className="sidebarFoot">
        <div className="adapterSelector">
          <label htmlFor="agent-adapter">Agent 运行模式</label>
          <select
            id="agent-adapter"
            value={adapter}
            disabled={busy || savingAdapter || !adapter}
            onChange={(event) => void selectAdapter(event.target.value as Adapter)}
          >
            <option value="" disabled>读取中…</option>
            <option value="deterministic">deterministic</option>
            <option value="openai-compatible">openai-compatible</option>
          </select>
          <small>{savingAdapter ? "切换中…" : "全局生效；模型配置来自后端环境变量"}</small>
          {adapterError && <small role="alert">{adapterError}</small>}
        </div>
        <div className="systemStatus">
          <i />
          系统运行正常 <span>v0.1</span>
        </div>
        <button
          className="identityButton"
          type="button"
          disabled={busy}
          onClick={() => setShowIdentityMenu((value) => !value)}
          aria-expanded={showIdentityMenu}
        >
          <span className="avatar">
            <Image src={identity.avatarUrl} alt="" width={64} height={64} />
          </span>
          <span>
            <strong>{identity.name}</strong>
            <small>{identity.role}</small>
          </span>
          <b>⌄</b>
        </button>
        {showIdentityMenu && (
          <div className="identityMenu">
            <small>Demo identity simulation</small>
            {identities.map((item) => (
              <button
                type="button"
                key={`${item.name}-${item.role}`}
                onClick={() => selectIdentity(item)}
                aria-current={item.name === identity.name ? "true" : undefined}
              >
                <span className="avatar">
                  <Image src={item.avatarUrl} alt="" width={64} height={64} />
                </span>
                <span>
                  {item.name}
                  <small>{item.role}</small>
                </span>
              </button>
            ))}
            <p>仅模拟查看权限，不连接或修改 ERP</p>
          </div>
        )}
      </div>
    </aside>
  );
}
