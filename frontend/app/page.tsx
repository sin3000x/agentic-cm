"use client";

import { useEffect, useMemo, useState } from "react";
import AppSidebar from "./app-sidebar";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? `http://localhost:${process.env.AGENTIC_CM_API_PORT ?? 8000}`;

type CaseStatus = "处理中" | "暂缓" | "已关闭";
type CaseRisk = "高" | "中" | "低";
type CaseSummary = { id:string; title:string; description:string; status:CaseStatus; risk:CaseRisk; owner:string; ownerRole:string; ownerInitial:string; customer:string; due:string; dueTone:"danger"|"warning"|"normal"|"muted"; phase:number; phaseLabel:string; updated:string; attention?:string };
type ApiCase = { id:string; title:string; description:string; status:"OPEN"|"PENDING"|"CLOSED"; phase:"INTAKE"|"MANIFEST_REVIEW"|"PATH_EXPLORATION"|"PROFESSIONAL_COMMITMENT"|"FINAL_REVIEW"; owner:string; owner_role:string; business_payload?:{customer?:string}; updated_at:string };

const casePresentation: Record<string, Pick<CaseSummary,"risk"|"due"|"dueTone"|"attention">> = {
  "CM-2026-014": {risk:"高",due:"3 天后",dueTone:"danger",attention:"2 项专业承诺待完成"},
  "CM-2026-012": {risk:"高",due:"已逾期 1 天",dueTone:"danger",attention:"等待供应商恢复时间证据"},
  "CM-2026-015": {risk:"中",due:"5 天后",dueTone:"warning",attention:"Case Owner 需批准方案 B"},
  "CM-2026-009": {risk:"中",due:"8 天后",dueTone:"normal"},
  "CM-2026-006": {risk:"低",due:"已完成",dueTone:"muted"},
};
const defaultPresentation: Pick<CaseSummary,"risk"|"due"|"dueTone"> = {risk:"中",due:"待确认",dueTone:"normal"};
const filters = ["全部","处理中","暂缓","已关闭"] as const;
const stages = ["受理","评审","探索","承诺","决策","验证"];
const demoIdentities = [
  {name:"陈澄",role:"订单统筹经理",avatar:"陈"},
  {name:"王淼",role:"主计划",avatar:"王"},
  {name:"林乔",role:"研发",avatar:"林"},
  {name:"赵宁",role:"供应经理",avatar:"赵"},
];

function StatusPill({status}:{status:CaseStatus}){return <span className={`statusPill status-${status}`}>{status}</span>}
function RiskMark({risk}:{risk:CaseRisk}){return <span className={`riskMark risk-${risk}`}><i />{risk}风险</span>}
function StageProgress({value,label}:{value:number;label:string}){return <div className="stageProgress" aria-label={`当前阶段：${label}`}><div>{stages.map((stage,index)=><i key={stage} className={index<value?"filled":""}/>)}</div><span>{label}</span></div>}

function mapCase(apiCase: ApiCase): CaseSummary {
  const status: Record<ApiCase["status"], CaseStatus> = {OPEN:"处理中",PENDING:"暂缓",CLOSED:"已关闭"};
  const phases: Record<ApiCase["phase"], {value:number;label:string}> = {
    INTAKE:{value:1,label:"Case 受理"},
    MANIFEST_REVIEW:{value:2,label:"Manifest 评审"},
    PATH_EXPLORATION:{value:3,label:"Path 探索"},
    PROFESSIONAL_COMMITMENT:{value:4,label:"专业承诺"},
    FINAL_REVIEW:{value:5,label:"最终决策"},
  };
  const currentPhase = apiCase.status === "CLOSED" ? {value:6,label:"结果验证"} : phases[apiCase.phase];
  const presentation = casePresentation[apiCase.id] ?? defaultPresentation;
  return {
    id:apiCase.id,title:apiCase.title,description:apiCase.description,status:status[apiCase.status],
    owner:apiCase.owner,ownerRole:apiCase.owner_role,ownerInitial:apiCase.owner.slice(0,1),
    customer:apiCase.business_payload?.customer ?? "内部协同",
    updated:new Date(apiCase.updated_at).toLocaleString("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"}),
    phase:currentPhase.value,phaseLabel:currentPhase.label,...presentation,
  };
}

export default function Home(){
  const [activeFilter,setActiveFilter]=useState<(typeof filters)[number]>("全部");
  const [search,setSearch]=useState("");
  const [selectedCase,setSelectedCase]=useState<CaseSummary|null>(null);
  const [identityIndex,setIdentityIndex]=useState(0);
  const [caseData,setCaseData]=useState<CaseSummary[]>([]);
  const [loadState,setLoadState]=useState<"loading"|"ready"|"error">("loading");
  const visibleCases=useMemo(()=>{const keyword=search.trim().toLowerCase();return caseData.filter(item=>(activeFilter==="全部"||item.status===activeFilter)&&(!keyword||[item.id,item.title,item.customer,item.owner].some(value=>value.toLowerCase().includes(keyword))))},[activeFilter,search,caseData]);
  const openCount=caseData.filter(item=>item.status==="处理中").length;

  useEffect(()=>{
    const controller=new AbortController();
    const loadCases=()=>fetch(`${API_BASE}/api/cases`,{signal:controller.signal})
      .then(response=>{if(!response.ok)throw new Error(`Case API ${response.status}`);return response.json() as Promise<ApiCase[]>})
      .then(cases=>{setCaseData(cases.map(mapCase));setLoadState("ready")})
      .catch(error=>{if(error instanceof DOMException&&error.name==="AbortError")return;setLoadState("error")});
    void loadCases();
    window.addEventListener("focus",loadCases);
    return()=>{controller.abort();window.removeEventListener("focus",loadCases)};
  },[]);

  return <div className="appShell">
    <AppSidebar active="overview" identity={demoIdentities[identityIndex]} identities={demoIdentities} onIdentitySelect={setIdentityIndex}/>

    <main className="mainArea">
      <header className="topbar"><div className="breadcrumb"><span>运营控制台</span><b>/</b>Case 总览</div><div className="topActions"><label className="globalSearch"><span>⌕</span><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="搜索 Case、客户或负责人" aria-label="搜索 Case"/><kbd>⌘ K</kbd></label><button className="iconButton" type="button" aria-label="通知">◔<i/></button><button className="createButton" type="button"><span>＋</span>新建 Case</button></div></header>
      <div className="pageContent">
        <section className="welcome"><div><p className="eyebrow">FRIDAY · AUG 21</p><h1>早上好，陈澄</h1><p className="welcomeCopy">今天有 <strong>3 个事项</strong>需要你的判断，其中 1 个 Case 已接近承诺期限。</p></div><div className="governanceNote"><span>Human governed</span><p>Agent 提案 · 人员决策 · 全程留痕</p></div></section>
        <section className="metrics" aria-label="Case 指标">
          <article><div className="metricIcon metricTeal">◎</div><div><span>进行中 Case</span><strong>{openCount}</strong><small><b>实时</b> 来自 Case API</small></div></article>
          <article><div className="metricIcon metricAmber">!</div><div><span>需要关注</span><strong>3</strong><small>1 个已逾期</small></div></article>
          <article><div className="metricIcon metricBlue">✓</div><div><span>本月已闭环</span><strong>12</strong><small><b>+18%</b> 环比</small></div></article>
          <article><div className="metricIcon metricViolet">↯</div><div><span>平均决策周期</span><strong>2.4<em>天</em></strong><small><b>−0.6 天</b> 较上月</small></div></article>
        </section>
        <div className="dashboardGrid">
          <section className="casePanel" id="case-overview">
            <div className="panelHeader"><div><h2>Case 总览</h2><p>跨组织异常处置的当前状态</p></div><button type="button">查看全部 <span>→</span></button></div>
            {loadState==="error"&&<div className="caseSyncNotice" role="alert">Case 状态同步失败，当前列表可能不是最新。</div>}
            <div className="caseToolbar"><div className="filterTabs" role="tablist" aria-label="按状态筛选">{filters.map(filter=><button key={filter} type="button" role="tab" aria-selected={activeFilter===filter} className={activeFilter===filter?"active":""} onClick={()=>setActiveFilter(filter)}>{filter}{filter==="全部"&&<span>{caseData.length}</span>}</button>)}</div><label className="tableSearch"><span>⌕</span><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="筛选当前列表" aria-label="筛选当前 Case 列表"/></label></div>
            <div className="caseTableWrap">
              <table className="caseTable">
                <thead><tr><th>CASE</th><th>状态 / 风险</th><th>当前阶段</th><th>负责人</th><th>承诺期限</th><th>最近更新</th><th><span className="srOnly">操作</span></th></tr></thead>
                <tbody>{visibleCases.map((item) => {
                  const hasWorkspace = item.id === "CM-2026-014";
                  const title = <><span className={`caseGlyph glyph-${item.risk}`}>◇</span><span><b>{item.title}</b><small>{item.id} · {item.customer}</small></span></>;
                  return <tr key={item.id}>
                    <td>{hasWorkspace
                      ? <a className="caseTitle" href={`/cases/${item.id}`} style={{color:"inherit",textDecoration:"none"}}>{title}</a>
                      : <div className="caseTitle">{title}</div>}
                    </td>
                    <td><StatusPill status={item.status}/><RiskMark risk={item.risk}/></td>
                    <td><StageProgress value={item.phase} label={item.phaseLabel}/></td>
                    <td><div className="ownerCell"><span className={`avatar avatar-${item.ownerInitial}`}>{item.ownerInitial}</span><span><b>{item.owner}</b><small>{item.ownerRole}</small></span></div></td>
                    <td><span className={`due due-${item.dueTone}`}>{item.due}</span></td>
                    <td><span className="updated">{item.updated}</span></td>
                    <td>{hasWorkspace
                      ? <a className="rowAction" href={`/cases/${item.id}`} style={{display:"grid",placeItems:"center",textDecoration:"none"}} aria-label={`打开 ${item.title}`}>›</a>
                      : <button className="rowAction" type="button" onClick={()=>setSelectedCase(item)} aria-label={`查看 ${item.title}`}>›</button>}
                    </td>
                  </tr>;
                })}</tbody>
              </table>
              {visibleCases.length===0&&<div className="emptyState"><span>⌕</span><strong>{loadState==="loading"?"正在同步 Case 状态":"没有匹配的 Case"}</strong><p>{loadState==="loading"?"状态与阶段以 Case API 为准":"尝试调整状态或搜索关键词"}</p></div>}
            </div>
            <div className="tableFooter"><span>显示 {visibleCases.length} / {caseData.length} 个 Case</span><div><button type="button" disabled>‹</button><button type="button" className="active">1</button><button type="button" disabled>›</button></div></div>
          </section>
          <aside className="rightRail">
            <section className="attentionCard" id="attention"><div className="railHeader"><div><span className="pulseDot"/><h2>需要你的关注</h2></div><b>3</b></div><div className="attentionList">{caseData.filter(item=>item.attention).map((item,index)=><button key={item.id} type="button" onClick={()=>setSelectedCase(item)}><span className={`attentionIndex attention-${index+1}`}>{index+1}</span><span><strong>{item.attention}</strong><small>{item.id} · {item.title}</small></span><em>{index===0?"今天":index===1?"已逾期":"待决策"}</em></button>)}</div><a href="#case-overview">进入我的待办 <span>→</span></a></section>
            <section className="activityCard" id="activity"><div className="railHeader"><div><h2>最新协作动态</h2></div><button type="button">全部</button></div><ol className="activityList"><li><span className="avatar avatar-blue">王</span><div><p><b>王淼</b> 提交了供应可行性承诺</p><small>CM-2026-014 · 12 分钟前</small></div></li><li><span className="activityAgent">A</span><div><p><b>Planning Agent</b> 生成 Manifest v2</p><small>CM-2026-012 · 28 分钟前</small></div></li><li><span className="avatar avatar-purple">林</span><div><p><b>林乔</b> 请求补充技术证据</p><small>CM-2026-015 · 1 小时前</small></div></li><li><span className="activityDone">✓</span><div><p><b>华南仓到货差异</b> 已完成验证</p><small>CM-2026-006 · 2 天前</small></div></li></ol></section>
          </aside>
        </div>
      </div>
    </main>
    {selectedCase&&<div className="drawerBackdrop"><button hidden type="button" onClick={()=>setSelectedCase(null)} aria-label="关闭快速查看"/><aside className="caseDrawer" role="dialog" aria-modal="true" aria-label={`${selectedCase.title} 快速查看`}><header><div><small>{selectedCase.id}</small><h2>{selectedCase.title}</h2></div><button type="button" onClick={()=>setSelectedCase(null)} aria-label="关闭">×</button></header><div className="drawerBody"><div className="drawerBadges"><StatusPill status={selectedCase.status}/><RiskMark risk={selectedCase.risk}/></div><p className="drawerDescription">{selectedCase.description}</p><dl><div><dt>当前阶段</dt><dd>{selectedCase.phaseLabel}</dd></div><div><dt>Case Owner</dt><dd>{selectedCase.owner} · {selectedCase.ownerRole}</dd></div><div><dt>业务对象</dt><dd>{selectedCase.customer}</dd></div><div><dt>承诺期限</dt><dd className={`due-${selectedCase.dueTone}`}>{selectedCase.due}</dd></div></dl><div className="drawerStage"><span>处置进度</span><StageProgress value={selectedCase.phase} label={selectedCase.phaseLabel}/></div>{selectedCase.attention&&<div className="drawerNotice"><span>!</span><div><strong>待处理</strong><p>{selectedCase.attention}</p></div></div>}</div><footer><button type="button" className="secondaryButton" onClick={()=>setSelectedCase(null)}>返回总览</button><button type="button" className="createButton">打开 Case 工作台 <span>→</span></button></footer></aside></div>}
  </div>
}
