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
  if (!selector) return <span className="assetSelector">未绑定场景</span>;
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
  return <article className={`assetCard${level ? ` skill-${level.toLowerCase().replace(" ", "-")}` : ""}`}>
    <header><div className={`assetKind kind-${group}`}>{group === "skills" ? "S" : group === "policies" ? "P" : "K"}</div><div>{level && <span className="assetLevel">{level}</span>}<h2>{asset.title}</h2><p>{asset.id} · v{asset.resolved_ref.version}</p></div><span className={`assetOrigin ${asset.resolved_ref.source}`}>{asset.resolved_ref.source === "local" ? "本地覆盖" : "内置"}</span></header>
    <Selector selector={asset.selector}/>
    <AssetBody group={group} asset={asset}/>
    {children}
    <footer><span>SHA-256</span><code>{asset.resolved_ref.digest.replace("sha256:", "").slice(0, 16)}</code></footer>
  </article>;
}

function assetMatches(asset: CapabilityAsset, keyword: string) {
  return !keyword || [asset.title, asset.id, asset.description, asset.content?.summary].some(value => value?.toLowerCase().includes(keyword));
}

function SkillHierarchy({ caseTypes, skills, search }: { caseTypes: CaseTypeCatalog[]; skills: CapabilityAsset[]; search: string }) {
  const keyword = search.trim().toLowerCase();
  const byId = new Map(skills.map(skill => [skill.id, skill]));
  const memberIds = new Set(skills.flatMap(skill => skill.members ?? []));
  const assignedTopLevel = new Set<string>();

  const trees = caseTypes.map(caseType => {
    const caseTypeMatch = !keyword || [caseType.case_type, caseType.title].some(value => value.toLowerCase().includes(keyword));
    const branches = caseType.paths.map(path => {
      const pathMatch = !keyword || [path.id, path.title, path.description].some(value => value.toLowerCase().includes(keyword));
      const nodes = skills.filter(skill =>
        !memberIds.has(skill.id)
        && skill.selector?.path_definition?.includes(path.id)
        && skill.selector?.case_type?.includes(caseType.case_type)
      ).map(skill => {
        assignedTopLevel.add(skill.id);
        const members = (skill.members ?? []).map(memberId => byId.get(memberId)).filter((member): member is CapabilityAsset => Boolean(member));
        const skillMatch = assetMatches(skill, keyword);
        const visibleMembers = caseTypeMatch || pathMatch || skillMatch ? members : members.filter(member => assetMatches(member, keyword));
        return { skill, members: visibleMembers, visible: caseTypeMatch || pathMatch || skillMatch || visibleMembers.length > 0 };
      }).filter(node => node.visible);
      return { path, nodes, visible: caseTypeMatch || pathMatch || nodes.length > 0 };
    }).filter(branch => branch.visible);
    return { caseType, branches, visible: caseTypeMatch || branches.length > 0 };
  }).filter(tree => tree.visible);

  const standalone = skills.filter(skill =>
    !memberIds.has(skill.id)
    && !assignedTopLevel.has(skill.id)
    && assetMatches(skill, keyword)
  );

  if (trees.length === 0 && standalone.length === 0) return null;
  return <>
    {trees.map(({ caseType, branches }) => <article className="caseTypeCard" key={caseType.case_type}>
      <header><div><span className="assetLevel">CASE TYPE</span><h2>{caseType.title}</h2><p>{caseType.case_type}</p></div><span className={`assetOrigin ${caseType.source}`}>{caseType.source === "local" ? "本地覆盖" : "内置"}</span></header>
      <div className="skillPathTree">{branches.map(({ path, nodes }) => <section className="skillPathBranch" key={path.id}>
        <header><span>PATH</span><div><h3>{path.title}</h3><code>{path.id}</code><p>{path.description}</p></div></header>
        <div className="skillPathCapabilities">{nodes.map(({ skill, members }) => <AssetCard key={skill.id} group="skills" asset={skill} level={skill.members ? "SKILL BUNDLE" : "ATOMIC SKILL"}>
          {skill.members && <div className="skillMembers"><p>组合成员 · 执行时随 Bundle 展开</p>{members.map(member => <AssetCard key={member.id} group="skills" asset={member} level="ATOMIC SKILL" />)}</div>}
        </AssetCard>)}</div>
      </section>)}</div>
    </article>)}
    {standalone.length > 0 && <section className="standaloneSkills"><header><span>STANDALONE</span><h2>独立 Skills</h2></header><div className="assetGrid">{standalone.map(skill => <AssetCard key={skill.id} group="skills" asset={skill} level="ATOMIC SKILL" />)}</div></section>}
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
  const skillHasMatch = group === "skills" && Boolean(data) && (data?.assets.skills.some(asset =>
    assetMatches(asset, search.trim().toLowerCase())
  ) || data?.case_types.some(caseType =>
    [caseType.case_type, caseType.title].some(value => value.toLowerCase().includes(search.trim().toLowerCase()))
    || caseType.paths.some(path => [path.id, path.title, path.description].some(value => value.toLowerCase().includes(search.trim().toLowerCase())))
  ) || !search.trim());
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
        {data && isEmpty && <div className="assetMessage"><strong>{search ? "没有匹配的资产" : copy.empty}</strong><p>{search ? "请尝试其他名称、ID、Path 或描述关键词。" : "发布资产后刷新即可显示。"}</p></div>}
        <section className={group === "skills" ? "skillHierarchy" : "assetGrid"} aria-live="polite">
          {group === "skills" && data && <SkillHierarchy caseTypes={data.case_types} skills={data.assets.skills} search={search} />}
          {group !== "skills" && assets.map(asset => <AssetCard group={group} asset={asset} key={asset.resolved_ref.id} />)}
        </section>
      </div>
    </main>
  </div>;
}
