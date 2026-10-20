"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";
import { useDemoIdentity, type SidebarIdentity } from "./lib/identities";

import { apiGet, apiPost } from "./lib/api";

type Adapter = "deterministic" | "openai-compatible";
type RuntimeConfig = { adapter: Adapter; model: string | null; model_default: string };

export type { SidebarIdentity };

type AppSidebarProps = {
  active: "none" | "overview" | "inbox" | "skills" | "policies" | "knowledge";
  inboxCount?: number | null;
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
  const [inbox, setInbox] = useState<{ role: string; count: number } | null>(null);
  const displayedInboxCount = inboxCount !== undefined
    ? inboxCount
    : inbox?.role === identity.role ? inbox.count : null;

  useEffect(() => {
    if (inboxCount !== undefined) return;
    const controller = new AbortController();
    apiGet<unknown[]>("/api/inbox", { role: identity.role }, controller.signal, "no-store")
      .then((items) => {
        if (!controller.signal.aborted) setInbox({ role: identity.role, count: items.length });
      })
      .catch(() => {
        if (!controller.signal.aborted) setInbox(null);
      });
    return () => controller.abort();
  }, [identity.role, active, busy, inboxCount]);


  const [adapter, setAdapter] = useState<Adapter | "">("");
  const [model, setModel] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelError, setModelError] = useState("");
  const [modelsRevision, setModelsRevision] = useState(0);
  const [savingAdapter, setSavingAdapter] = useState(false);
  const [adapterError, setAdapterError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiGet<RuntimeConfig>("/api/runtime-config", undefined, undefined, "no-store")
      .then((config) => {
        if (!cancelled) {
          setLoadingModels(true);
          setAdapter(config.adapter);
          setModel(config.model ?? "");
          setDefaultModel(config.model_default);
        }
      })
      .catch(() => { if (!cancelled) setAdapterError("无法读取运行模式，请刷新重试"); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!adapter) return;
    const controller = new AbortController();
    apiGet<{ data: { id: string }[] }>("/api/models", undefined, controller.signal, "no-store")
      .then((result) => {
        if (!controller.signal.aborted) {
          setModels(result.data.map((item) => item.id));
          if (!result.data.length) setModelError("模型服务未返回可选模型");
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setModels([]);
          setModelError(error instanceof Error ? error.message : "无法获取模型列表");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoadingModels(false); });
    return () => controller.abort();
  }, [adapter, modelsRevision]);

  async function selectAdapter(value: Adapter, selectedModel?: string) {
    setSavingAdapter(true);
    setAdapterError("");
    try {
      const config = await apiPost<RuntimeConfig>("/api/runtime-config", { adapter: value, model: selectedModel });
      if (config.adapter !== adapter) {
        setLoadingModels(true);
        setModelError("");
      }
      setAdapter(config.adapter);
      setModel(config.model ?? "");
      setDefaultModel(config.model_default);
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
          {displayedInboxCount !== null && <b>{displayedInboxCount}</b>}
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
        <Link className="navLink" href="/about">
          <span className="navIcon">ⓘ</span>关于项目
        </Link>
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
          <small>{savingAdapter ? "切换中…" : "全局生效"}</small>
          {adapter && (
            <>
              <label htmlFor="agent-model">Agent 模型</label>
              <select
                id="agent-model"
                value={model}
                disabled={busy || savingAdapter || loadingModels || !models.length}
                onChange={(event) => void selectAdapter(adapter, event.target.value)}
              >
                <option value="" disabled>环境配置{defaultModel ? `（${defaultModel}）` : ""}</option>
                {model && !models.includes(model) && <option value={model} disabled>{model}（当前配置）</option>}
                {models.map((id) => <option key={id} value={id}>{id}</option>)}
              </select>
              <small>{loadingModels ? "正在获取模型列表…" : "用于 OpenAI-compatible 模式的所有 Agent"}</small>
              <button
                type="button"
                className="modelRefresh"
                disabled={busy || savingAdapter || loadingModels}
                onClick={() => {
                  setLoadingModels(true);
                  setModelError("");
                  setModelsRevision((value) => value + 1);
                }}
              >刷新模型列表</button>
              {modelError && <small role="alert">{modelError}</small>}
            </>
          )}
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
          </div>
        )}
      </div>
    </aside>
  );
}
