"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import AppSidebar from "../app-sidebar";
import { apiGet, isAbort } from "../lib/api";
import { coreDemoIdentities as demoIdentities } from "../lib/identities";

export type AssetGroup = "skills" | "policies" | "knowledge";

type AssetRef = { id: string; version: string; digest: string; source: "builtin" | "local" };
type Commitment = { id: string; role: string; review_dimension: string; depends_on?: string[] };
type PathDefinition = { id: string; title: string; description: string };
type CaseTypeCatalog = { case_type: string; title: string; paths: PathDefinition[]; source: "builtin" | "local" };
type CapabilityAsset = {
  id: string;
  title: string;
  description?: string;
  kind?: "atomic" | "bundle";
  maintainer_role?: string | null;
  selector?: Record<string, string[]> | null;
  instructions_markdown?: string;
  files?: Array<{ path: string }>;
  members?: string[];
  requirements?: { commitments?: Commitment[] };
  confidence?: string;
  source?: { type?: string; case_id?: string; observed_at?: string; reviewed_by?: string };
  content?: { summary?: string; observations?: string[] };
  resolved_ref: AssetRef;
};

type LibraryResponse = {
  assets: Record<AssetGroup, CapabilityAsset[]>;
  counts: Record<AssetGroup, number>;
  case_types: CaseTypeCatalog[];
};

const groupCopy = {
  skills: {
    eyebrow: "AGENT METHODS",
    title: "Skills",
    description: "Agent 可调用的标准 SKILL.md 方法包。它们负责分析与提案，不替代业务人员作出承诺。",
    empty: "后台当前没有已发布的 Skill。",
  },
  policies: {
    eyebrow: "GOVERNANCE RULES",
    title: "Policies",
    description: "平台强制执行的责任、评审与依赖规则，会确定性编译为 Case 中的 CommitmentDAG。",
    empty: "后台当前没有已发布的 Policy。",
  },
  knowledge: {
    eyebrow: "ADVISORY CONTEXT",
    title: "Knowledge",
    description: "带来源和审核信息的组织经验，只作为建议材料，不会覆盖当前 Case 事实。",
    empty: "后台当前没有已发布的 Knowledge。",
  },
} as const;

function Selector({ selector }: { selector?: Record<string, string[]> | null }) {
  if (!selector) return null;
  return <div className="assetSelectors">{Object.entries(selector).map(([key, values]) => <span key={key}>{key}: {values.join(", ")}</span>)}</div>;
}

function AssetBody({ group, asset }: { group: AssetGroup; asset: CapabilityAsset }) {
  if (group === "skills") return <>
    <p className="assetSummary">{asset.description}</p>
    <details><summary>查看 SKILL.md 指令与文件</summary><pre>{asset.instructions_markdown}</pre><p className="assetFiles">{asset.files?.map(file => file.path).join(" · ")}</p></details>
  </>;
  if (group === "policies") return <div className="commitmentList">{asset.requirements?.commitments?.map(node => <div key={node.id}><strong>{node.id}</strong><p>{node.role} · {node.review_dimension}</p><small>{node.depends_on?.length ? `依赖 ${node.depends_on.join("、")}` : "无前置依赖"}</small></div>)}</div>;
  const sourceType = asset.source?.type === "closed_case" ? "已关闭 Case" : asset.source?.type;
  const confidence = asset.confidence === "medium" ? "中" : asset.confidence === "high" ? "高" : asset.confidence === "low" ? "低" : asset.confidence;
  return <>
    <p className="assetSummary">{asset.content?.summary}</p>
    <ul className="knowledgeObservations">{asset.content?.observations?.map(item => <li key={item}>{item}</li>)}</ul>
    <dl className="knowledgeSource"><div><dt>来源</dt><dd>{sourceType}{asset.source?.case_id ? ` · ${asset.source.case_id}` : ""}</dd></div><div><dt>观察日期</dt><dd>{asset.source?.observed_at ?? "—"}</dd></div><div><dt>审核</dt><dd>{asset.source?.reviewed_by ?? "—"}</dd></div><div><dt>置信度</dt><dd>{confidence ?? "—"}</dd></div></dl>
  </>;
}

function AssetCard({ group, asset, level, children }: { group: AssetGroup; asset: CapabilityAsset; level?: string; children?: ReactNode }) {
  const skillKind = asset.kind === "bundle" || (asset.members && asset.members.length > 0) ? "SKILL BUNDLE" : "ATOMIC SKILL";
  return <article className={`assetCard${level ? ` skill-${level.toLowerCase().replace(" ", "-")}` : ""}`}>
    <header><div className={`assetKind kind-${group}`}>{group === "skills" ? "S" : group === "policies" ? "P" : "K"}</div><div>{group === "skills" && <span className="assetLevel">{level ?? skillKind}</span>}<h2>{asset.title}</h2><p>{asset.id} · v{asset.resolved_ref.version}</p></div><span className={`assetOrigin ${asset.resolved_ref.source}`}>{asset.resolved_ref.source === "local" ? "本地覆盖" : "内置"}</span></header>
    {group === "skills" ? <p className="assetSelector">维护角色 · {asset.maintainer_role?.trim() || "平台公共能力"}</p> : <Selector selector={asset.selector}/>}
    <AssetBody group={group} asset={asset}/>
    {children}
    <footer><span>SHA-256</span><code>{asset.resolved_ref.digest.replace("sha256:", "").slice(0, 16)}</code></footer>
  </article>;
}

function assetMatches(asset: CapabilityAsset, keyword: string) {
  return !keyword || [asset.title, asset.id, asset.description, asset.content?.summary].some(value => value?.toLowerCase().includes(keyword));
}

const publicRole = "平台公共能力";

function skillRole(skill: CapabilityAsset) {
  return skill.maintainer_role?.trim() || publicRole;
}

function skillMatchesSearch(skill: CapabilityAsset, keyword: string, byId: Map<string, CapabilityAsset>) {
  if (!keyword) return true;
  if (assetMatches(skill, keyword) || skillRole(skill).toLowerCase().includes(keyword)) return true;
  return (skill.members ?? []).some(memberId => {
    const member = byId.get(memberId);
    return Boolean(member && (assetMatches(member, keyword) || skillRole(member).toLowerCase().includes(keyword)));
  });
}

function SkillRoleLibrary({ skills, search }: { skills: CapabilityAsset[]; search: string }) {
  const keyword = search.trim().toLowerCase();
  const byId = new Map(skills.map(skill => [skill.id, skill]));
  const visibleSkills = skills.filter(skill => skillMatchesSearch(skill, keyword, byId));
  const roleGroups = visibleSkills.reduce((groups, skill) => {
    const role = skillRole(skill);
    const current = groups.get(role) ?? [];
    current.push(skill);
    groups.set(role, current);
    return groups;
  }, new Map<string, CapabilityAsset[]>());
  const namedRoles = [...roleGroups.keys()].filter(role => role !== publicRole).sort((left, right) => left.localeCompare(right, "zh"));
  const orderedRoles = roleGroups.has(publicRole) ? [...namedRoles, publicRole] : namedRoles;

  if (orderedRoles.length === 0) return null;
  return <>
    {orderedRoles.map(role => {
      const roleSkills = [...(roleGroups.get(role) ?? [])].sort((left, right) => left.title.localeCompare(right.title, "zh"));
      return <section className="skillRoleGroup" key={role}>
        <header className="skillRoleHeader"><div><span className="assetLevel">MAINTAINER ROLE</span><h2>{role}</h2></div><small>{roleSkills.length} 项</small></header>
        <div className="skillRoleGrid">{roleSkills.map(skill => {
          const members = (skill.members ?? []).map(memberId => byId.get(memberId)).filter((member): member is CapabilityAsset => Boolean(member));
          return <AssetCard key={skill.id} group="skills" asset={skill} level={skill.kind === "bundle" || members.length > 0 ? "SKILL BUNDLE" : "ATOMIC SKILL"}>
            {members.length > 0 && <div className="skillMemberRefs"><p>组合成员 · 仅作为 Bundle 引用</p>{members.map(member => <div className="skillMemberRef" key={member.id}><span><strong>{member.title}</strong><small>{member.id}</small></span><em>成员维护 · {skillRole(member)}</em></div>)}</div>}
          </AssetCard>;
        })}</div>
      </section>;
    })}
  </>;
}

export default function AssetLibrary({ group }: { group: AssetGroup }) {
  const [identityIndex, setIdentityIndex] = useState(0);
  const [data, setData] = useState<LibraryResponse | null>(null);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState("");
  const copy = groupCopy[group];

  useEffect(() => {
    const controller = new AbortController();
    apiGet<LibraryResponse>("/api/capabilities", undefined, controller.signal)
      .then(setData)
      .catch(reason => { if (!isAbort(reason)) setError(true); });
    return () => controller.abort();
  }, []);

  const assets = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return (data?.assets[group] ?? []).filter(asset => assetMatches(asset, keyword));
  }, [data, group, search]);
  const skillById = useMemo(() => new Map((data?.assets.skills ?? []).map(skill => [skill.id, skill])), [data]);
  const skillHasMatch = group === "skills" && Boolean(data) && (
    !search.trim()
    || data.assets.skills.some(asset => skillMatchesSearch(asset, search.trim().toLowerCase(), skillById))
  );
  const isEmpty = group === "skills" ? !skillHasMatch : assets.length === 0;

  return <div className="appShell">
    <AppSidebar active={group} identity={demoIdentities[identityIndex]} identities={demoIdentities} inboxCount={3} onIdentitySelect={setIdentityIndex}/>
    <main className="mainArea">
      <header className="topbar"><div className="breadcrumb"><span>组织资产</span><b>/</b>{copy.title}</div><div className="assetTopStatus"><i />后台资产库 · 只读</div></header>
      <div className="assetPage">
        <section className="assetHero"><div><p className="eyebrow">{copy.eyebrow}</p><h1>{copy.title}</h1><p>{copy.description}</p></div><label className="assetSearch"><span>⌕</span><input value={search} onChange={event => setSearch(event.target.value)} placeholder={`搜索 ${copy.title}`} aria-label={`搜索 ${copy.title}`}/></label></section>
        {data && <section className="assetStats" aria-label="组织资产统计">
          <a className={group === "skills" ? "active" : ""} href="/assets/skills"><span>Skills</span><strong>{data.counts.skills}</strong></a>
          <a className={group === "policies" ? "active" : ""} href="/assets/policies"><span>Policies</span><strong>{data.counts.policies}</strong></a>
          <a className={group === "knowledge" ? "active" : ""} href="/assets/knowledge"><span>Knowledge</span><strong>{data.counts.knowledge}</strong></a>
        </section>}
        {error && <div className="assetMessage error"><strong>无法读取后台资产</strong><p>请确认 Agentic CM API 已启动并可从当前页面访问。</p></div>}
        {!data && !error && <div className="assetMessage"><strong>正在读取后台资产…</strong><p>数据来自当前运行中的 CapabilityRegistry。</p></div>}
        {data && isEmpty && <div className="assetMessage"><strong>{search ? "没有匹配的资产" : copy.empty}</strong><p>{search ? "请尝试其他名称、ID、Role 或描述关键词。" : "发布资产后刷新即可显示。"}</p></div>}
        <section className={group === "skills" ? "skillRoleLibrary" : "assetGrid"} aria-live="polite">
          {group === "skills" && data && <SkillRoleLibrary skills={data.assets.skills} search={search} />}
          {group !== "skills" && assets.map(asset => <AssetCard group={group} asset={asset} key={asset.resolved_ref.id} />)}
        </section>
      </div>
    </main>
  </div>;
}
