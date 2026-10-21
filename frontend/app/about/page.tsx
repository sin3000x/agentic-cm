"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { botAvatars, personAvatars } from "../lib/identities";
import "./about.css";

const chapters = ["封面", "流程与 Case", "角色与求解", "能力与责任", "平台资产", "Case 工作流", "技术架构"];

function Slide({ number, title, children, note, presentingSlide }: { presentingSlide: number | null; number: number; title: ReactNode; children: ReactNode; note?: string }) {
  return <section className={`aboutSlide${number === 1 ? " aboutCover" : ""}${presentingSlide !== null && presentingSlide !== number ? " aboutSlideInactive" : ""}`} id={`slide-${number}`} aria-labelledby={`heading-${number}`}>
    <div className="aboutSlideBody">
      {number === 1 && <div className="aboutCoverEyebrow"><span/> AGENTIC CM <span className="aboutCoverEdition">平台介绍</span></div>}
      {number === 1 ? <h1 id={`heading-${number}`}>{title}</h1> : <h2 id={`heading-${number}`}>{title}</h2>}
      {children}
      {note && <p className={`aboutNote${number === 4 ? " aboutNoteEmphasis" : ""}`}>{note}</p>}
    </div>
    <footer className="aboutSlideFooter"><span>{String(number).padStart(2, "0")} / {String(chapters.length).padStart(2, "0")}</span></footer>
  </section>;
}

function Diagram({ label, children, height = 360, inset = 0 }: { label: string; children: ReactNode; height?: number; inset?: number }) {
  const id = useId().replace(/:/g, "");
  // A scrollable diagram needs keyboard focus so arrow keys can pan it on narrow screens.
  // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
  return <div className="aboutDiagramScroll" tabIndex={0} role="region" aria-label={label}><svg className="aboutDiagram" viewBox={`${-inset} 0 ${1080 + inset * 2} ${height}`} role="img" aria-labelledby={id}><title id={id}>{label}</title>{children}</svg></div>;
}
function NodeIcon({ name, x, y }: { name: "event" | "people" | "owner"; x: number; y: number }) {
  const paths = {
    event: "M12 3 2 8l10 5 10-5-10-5ZM2 8v9l10 5 10-5V8M12 13v9M7 5.5l10 5",
    people: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM2 21v-2a7 7 0 0 1 14 0v2M17 4a4 4 0 0 1 0 8M19 15a6 6 0 0 1 3 5",
    owner: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM2 21v-2a7 7 0 0 1 11-5.7M15 18l3 3 5-6",
  };
  return <svg x={x} y={y} width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}

function ArchitectureIcon({ name, x, y, size = 26 }: { name: string; x: number; y: number; size?: number }) {
  const paths: Record<string, string> = {
    monitor: "M3 4h18v13H3zM8 21h8M12 17v4M6 8h5M6 11h9",
    api: "m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18",
    workflow: "M9 3h6v6H9zM2 15h6v6H2zM16 15h6v6h-6zM12 9v3M5 15v-3h14v3",
    people: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM2 21v-2a7 7 0 0 1 14 0v2M17 4a4 4 0 0 1 0 8M19 15a6 6 0 0 1 3 5",
    shield: "m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4Zm-4 10 3 3 5-6",
    layers: "m12 2-10 5 10 5 10-5-10-5ZM2 12l10 5 10-5M2 17l10 5 10-5",
    archive: "M3 3h18v5H3zM5 8v13h14V8M9 12h6M9 16h6",
    database: "M21 5c0 2-4 3-9 3S3 7 3 5s4-3 9-3 9 1 9 3ZM3 5v14c0 2 4 3 9 3s9-1 9-3V5M3 12c0 2 4 3 9 3s9-1 9-3",
    folder: "M3 5h7l2 3h9v13H3V5ZM7 12h10M7 16h6",
    cpu: "M6 6h12v12H6zM9 9h6v6H9zM9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4M18 9h4m-4 6h4",
  };
  return <svg x={x} y={y} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}

function Box({ x, y, w = 160, h = 62, title, sub, tone = "plain", icon, avatar }: { x: number; y: number; w?: number; h?: number; title: string; sub?: string; tone?: "plain" | "green" | "gold"; icon?: "event" | "people" | "owner"; avatar?: string }) {
  return <g className={`diagramBox ${tone}${avatar ? " personBox" : ""}`}><rect x={x} y={y} width={w} height={h} rx="9"/>{avatar && <image href={avatar} x={x + 9} y={y + h / 2 - 22} width="44" height="44" preserveAspectRatio="xMidYMid slice" style={{ clipPath: "circle(50%)" }}/>}{icon && <NodeIcon name={icon} x={x + 15} y={y + h / 2 - 18}/>}<text x={x + w / 2 + (icon || avatar ? 23 : 0)} y={y + h / 2 + (sub ? -8 : 1)} dominantBaseline="middle" textAnchor="middle" className="boxTitle">{title}</text>{sub && <text x={x + w / 2 + (icon || avatar ? 23 : 0)} y={y + h / 2 + 19} textAnchor="middle" className="boxSub">{sub}</text>}</g>;
}
function AgentBox({ x, y, w, h = 82, title, sub, agent }: { x: number; y: number; w: number; h?: number; title: string; sub?: string; agent: keyof typeof botAvatars }) {
  return <g className={`diagramBox agentBox agent-${agent}`}>
    <rect x={x} y={y} width={w} height={h} rx="12"/>
    <circle cx={x + (sub ? 40 : 33)} cy={y + h / 2} r={sub ? 31 : 25} fill="#ffffff" fillOpacity=".95"/>
    <image href={botAvatars[agent]} x={x + (sub ? 11 : 10)} y={y + h / 2 - (sub ? 32 : 26)} width={sub ? 58 : 46} height={sub ? 64 : 52} preserveAspectRatio="xMidYMid meet"/>
    <text x={x + (sub ? 92 : 68)} y={y + h / 2 + (sub ? -7 : 1)} dominantBaseline={sub ? undefined : "middle"} className="boxTitle">{title}</text>
    {sub && <text x={x + 92} y={y + h / 2 + 20} className="boxSub">{sub}</text>}
  </g>;
}

function Line({ d, dashed = false, gold = false, arrow = "end" }: { d: string; dashed?: boolean; gold?: boolean; arrow?: "end" | "both" | "none" }) {
  const id = useId().replace(/:/g, "");
  const color = gold ? "#a57730" : "#648b7d";
  return <g><defs><marker id={id} markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto-start-reverse"><path d="M0 0 9 4.5 0 9Z" fill={color}/></marker></defs><path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" strokeDasharray={dashed ? "6 5" : undefined} markerStart={arrow === "both" ? `url(#${id})` : undefined} markerEnd={arrow !== "none" ? `url(#${id})` : undefined}/></g>;
}
function Text({ x, y, children, small = false, anchor = "middle" }: { x: number; y: number; children: ReactNode; small?: boolean; anchor?: "start" | "middle" | "end" }) {
  return <text x={x} y={y} textAnchor={anchor} className={small ? "diagramSmall" : "diagramText"}>{children}</text>;
}

export default function AboutPage() {
  const [presenting, setPresenting] = useState(false);
  const [currentSlide, setCurrentSlide] = useState(1);
  const pageRef = useRef<HTMLDivElement>(null);
  const playButtonRef = useRef<HTMLButtonElement>(null);
  const deckRef = useRef<HTMLElement>(null);
  const moveSlide = useCallback((delta: number) => {
    setCurrentSlide((current) => Math.max(1, Math.min(chapters.length, current + delta)));
  }, []);
  const stopPresentation = useCallback(() => {
    setPresenting(false);
    if (document.fullscreenElement === pageRef.current) {
      void document.exitFullscreen().catch(() => {});
    }
    playButtonRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    if (!presenting) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    deckRef.current?.focus();
    const onFullscreenChange = () => {
      if (!document.fullscreenElement) stopPresentation();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "Escape") stopPresentation();
      else if (["ArrowRight", "ArrowDown", "PageDown"].includes(event.key)) moveSlide(1);
      else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(event.key)) moveSlide(-1);
      else if (event.key === " " && !(event.target instanceof HTMLButtonElement)) moveSlide(1);
      else if (event.key === "Home") setCurrentSlide(1);
      else if (event.key === "End") setCurrentSlide(chapters.length);
      else return;
      event.preventDefault();
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [presenting, moveSlide, stopPresentation]);

  async function startPresentation() {
    const slides = pageRef.current?.querySelectorAll<HTMLElement>(".aboutSlide");
    const nearest = slides && Array.from(slides).reduce((best, slide) =>
      Math.abs(slide.getBoundingClientRect().top) < Math.abs(best.getBoundingClientRect().top) ? slide : best);
    setCurrentSlide(nearest ? Number(nearest.id.replace("slide-", "")) : 1);
    setPresenting(true);
    try {
      await pageRef.current?.requestFullscreen?.();
    } catch {
      // Keep the viewport presentation available when native fullscreen is denied.
    }
  }

  return <div ref={pageRef} className={`aboutPage${presenting ? " aboutPresenting" : ""}`}>
    <div className="aboutToolbar"><Link href="/">← 返回工作台</Link><span>关于 Agentic CM · {chapters.length} 页演示</span><div className="aboutToolbarActions"><button ref={playButtonRef} type="button" onClick={startPresentation}>全屏播放 ▷</button><button type="button" onClick={() => window.print()}>导出 PDF slides ↗</button></div></div>
    <div className="aboutGuide"><span>导出时选择「另存为 PDF」，关闭页眉和页脚</span><nav aria-label="About 章节">{chapters.map((chapter, index) => <a key={chapter} href={`#slide-${index + 1}`}>{String(index + 1).padStart(2, "0")} {chapter}</a>)}</nav></div>
    <main ref={deckRef} tabIndex={-1} className="aboutDeck">
      <Slide presentingSlide={presenting ? currentSlide : null} number={1} title={<><span>基于事件的</span><span>多角色、多agent</span><span>协同平台</span></>}>
        <svg className="aboutCoverArtwork" viewBox="0 0 480 650" preserveAspectRatio="xMidYMid slice" fill="none" aria-hidden="true">
          <defs>
            <radialGradient id="cover-glow"><stop stopColor="#78ac92" stopOpacity=".3"/><stop offset="1" stopColor="#173f36" stopOpacity="0"/></radialGradient>
            <pattern id="cover-grid" width="32" height="32" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#b7d0c2" fillOpacity=".18"/></pattern>
          </defs>
          <path fill="#173f36" d="M0 0h480v650H0z"/>
          <path fill="url(#cover-grid)" d="M0 0h480v650H0z"/>
          <circle cx="240" cy="310" r="270" fill="url(#cover-glow)"/>
          <g stroke="#9bc0ab" strokeOpacity=".2"><circle cx="240" cy="310" r="112"/><circle cx="240" cy="310" r="204"/><path d="M36 310h408M240 106v408" strokeDasharray="3 9"/></g>
          <g stroke="#87b69e" strokeWidth="1.5"><path d="m240 310-131-124m131 124 139-91m-139 91 121 155m-121-155-145 97"/><path d="m109 186 270 33-18 246L95 407Z" strokeOpacity=".45" strokeDasharray="5 8"/></g>
          <g fill="#c3a56c"><circle cx="176" cy="249" r="4"/><circle cx="308" cy="266" r="4"/><circle cx="298" cy="385" r="4"/><circle cx="168" cy="358" r="4"/></g>
          <rect x="184" y="254" width="112" height="112" rx="28" fill="#e9eee2"/>
          <rect x="196" y="266" width="88" height="88" rx="21" stroke="#b4c8b9"/>
          <g stroke="#28594a" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m240 284-25 15 25 15 25-15-25-15Z"/><path d="m215 310 25 15 25-15m-50 11 25 15 25-15"/></g>
          {[{x:109,y:186,human:true},{x:379,y:219,human:false},{x:361,y:465,human:true},{x:95,y:407,human:false}].map(({x,y,human}) => <g key={x} transform={`translate(${x} ${y})`}>
            <circle r="34" fill="#214e41" stroke="#79a58e" strokeWidth="1.5"/>
            {human ? <g stroke="#e4e9dc" strokeWidth="2" strokeLinecap="round"><circle cy="-7" r="7"/><path d="M-14 15v-3a14 14 0 0 1 28 0v3"/></g> : <g stroke="#e4e9dc" strokeWidth="2" strokeLinecap="round"><rect x="-15" y="-10" width="30" height="24" rx="7"/><path d="M0-10v-6m-19 16h4m30 0h4M-6 7H6"/><circle cx="-6" cy="-1" r="1.5" fill="#e4e9dc"/><circle cx="6" cy="-1" r="1.5" fill="#e4e9dc"/></g>}
          </g>)}
          <path d="M42 54h28m-14-14v28M416 580h28m-14-14v28" stroke="#c3a56c" strokeWidth="1.5"/>
          <text x="42" y="605" fill="#b7d0c2" fontSize="11" letterSpacing="3">EVENT · HUMAN · AGENT</text>
        </svg>
        <dl className="aboutCoverDetails">
          <div><dt>部门</dt><dd>［部门名称］</dd></div>
          <div><dt>汇报人</dt><dd>［汇报人姓名］</dd></div>
          <div><dt>日期</dt><dd>［YYYY 年 MM 月 DD 日］</dd></div>
        </dl>
      </Slide>
      <Slide presentingSlide={presenting ? currentSlide : null} number={2} title="业务流程 vs 事件驱动">
        <Diagram label="复杂 SOP 按预定义的条件分支、核验与返工规则推进；事件驱动的 Case 围绕目标探索提拉、替代等路径，每条路径围绕假设连接事实、约束、角色反馈与待补信息，随新信息调整探索方向，最终由人确认承诺并决策闭环" height={465}>
          <g className="processComparison">
            <rect className="diagramPanel" x="0" y="0" width="510" height="350" rx="14"/><rect className="diagramPanel" x="540" y="0" width="540" height="350" rx="14"/>
            <Text x={255} y={36}>Business Process · 预定义 SOP</Text>
            <Line d="M120 94H154"/><Line d="M252 94H292"/><Line d="M368 94H406"/>
            <Line d="M330 119V151"/><Line d="M282 170H204V113" dashed/>
            <Line d="M448 111V211"/><Line d="M410 236H368"/><Line d="M292 236H254"/>
            <Line d="M330 261V304H406"/><Line d="M204 253V287"/><Line d="M254 304H406"/>
            <Line d="M156 304H136V236H154" dashed/>
            <Box x={24} y={77} w={96} h={34} title="接收订单"/><Box x={156} y={77} w={96} h={34} title="核验条件"/>
            <path className="sopDecision" d="M330 69 368 94 330 119 292 94Z"/><text className="boxTitle" x="330" y="95" textAnchor="middle" dominantBaseline="middle">齐备？</text>
            <Box x={408} y={77} w={80} h={34} title="订单确认"/><Box x={282} y={153} w={96} h={34} title="补充资料"/>
            <Box x={410} y={219} w={78} h={34} title="供需核验"/>
            <path className="sopDecision" d="M330 211 368 236 330 261 292 236Z"/><text className="boxTitle" x="330" y="237" textAnchor="middle" dominantBaseline="middle">满足？</text>
            <Box x={156} y={219} w={98} h={34} title="采购 / 替代"/><Box x={156} y={287} w={98} h={34} title="变更审批"/><Box x={408} y={287} w={80} h={34} title="执行交付" tone="green"/>
            <Text x={388} y={83} small>是</Text><Text x={345} y={140} small>否</Text><Text x={246} y={158} small>补齐重验</Text>
            <Text x={274} y={225} small>否</Text><Text x={345} y={280} small>是</Text><Text x={111} y={277} small>退回</Text>
            <Text x={255} y={338} small>分支、审批、返工规则事先定义</Text>

            <Text x={810} y={36}>Case Management · 目标驱动</Text>
            <Box x={552} y={175} w={66} h={52} title="事件"/><Box x={998} y={175} w={70} h={52} title="目标" tone="green"/>
            <Line d="M618 186C642 186 622 103 650 103M618 201H650M618 216C642 216 622 283 650 283" dashed arrow="none"/>
            <Line d="M958 103C986 103 970 185 996 185M958 193C978 193 978 201 996 201M958 283C986 283 970 217 996 217" dashed/>
            {[
              { y: 58, title: "提拉可行？", evidence: ["产能余量", "交期约束", "供应商反馈", "待补信息？"] },
              { y: 148, title: "能否替代？", evidence: ["物料特性", "客户要求", "研发意见", "待验证？"] },
              { y: 238, title: "还有别的解？", evidence: ["新线索", "资源约束", "角色反馈", "未知因素？"] },
            ].map(({ y, title, evidence }, index) => <g key={title} className="caseExploration">
              <ellipse className="caseExplorationBoundary" cx="804" cy={y + 45} rx="154" ry="43"/>
              <path className="caseEvidenceLink" d={`M696 ${y + 26}Q751 ${y + 16} 780 ${y + 41}M708 ${y + 70}Q750 ${y + 80} 780 ${y + 50}M829 ${y + 40}Q856 ${y + 15} 884 ${y + 22}M830 ${y + 51}Q859 ${y + 73} 883 ${y + 69}M700 ${y + 30}Q677 ${y + 49} 708 ${y + 66}M885 ${y + 26}Q917 ${y + 45} 885 ${y + 65}`}/>
              <ellipse className="caseHypothesis" cx="804" cy={y + 45} rx="50" ry="17"/>
              <text className="caseHypothesisTitle" x="804" y={y + 46} textAnchor="middle" dominantBaseline="middle">{title}</text>
              {[{ x: 696, dy: 26 }, { x: 708, dy: 70 }, { x: 884, dy: 22 }, { x: 883, dy: 69 }].map(({ x, dy }, i) => <g key={evidence[i]} className={i === 3 ? "caseUnknownEvidence" : "caseKnownEvidence"}>
                <circle cx={x} cy={y + dy} r="4"/>
                <text x={x + (i < 2 ? -8 : 8)} y={y + dy + 4} textAnchor={i < 2 ? "end" : "start"}>{evidence[i]}</text>
              </g>)}
              <text className="caseExplorationLabel" x="804" y={y + 14} textAnchor="middle">{index < 2 ? `探索 ${index === 0 ? "A" : "B"}` : "新方向 · 随信息浮现"}</text>
            </g>)}
            <Text x={810} y={344} small>补充事实 · 调整假设 · 发现新路径</Text>
          </g>
          <Line d="M255 356V365Q255 375 265 375H800Q810 375 810 365V356" arrow="none"/>
          <Line d="M540 375V391"/>
          <Box x={0} y={399} w={1080} h={62} title="关闭 Case：多角色沟通 → 方案与承诺确认 → Case Owner 决策闭环" tone="green"/>
        </Diagram>
      </Slide>
      <Slide presentingSlide={presenting ? currentSlide : null} number={3} title="按人拆 vs 按路径拆">
        <Diagram label="角色数字分身以订单经理为中心，与主计划、研发、供应经理和物流构成协作网络，仍需沟通交接确认；按提拉、替代等问题组织 Agent，可以跨学科整合求解" height={465}>
          <rect className="diagramPanel" x="0" y="0" width="520" height="399" rx="14"/><rect className="diagramPanel" x="560" y="0" width="520" height="399" rx="14"/>
          <Text x={260} y={45}>按角色复制数字分身</Text><Text x={820} y={45}>按问题组织求解 Agent</Text>
          <Line d="M198 111H322" arrow="both" dashed/><Line d="M198 303H322" arrow="both" dashed/>
          <Line d="M107 148V266" arrow="both" dashed/><Line d="M413 148V266" arrow="both" dashed/>
          <Line d="M150 148L207 168" arrow="both"/><Line d="M370 148L313 168" arrow="both"/>
          <Line d="M150 266L207 246" arrow="both"/><Line d="M370 266L313 246" arrow="both"/>
          <Box x={24} y={80} w={166} h={62} title="主计划 Agent" avatar={personAvatars["王淼"]}/><Box x={330} y={80} w={166} h={62} title="供应经理 Agent" avatar={personAvatars["赵宁"]}/>
          <Box x={165} y={176} w={190} h={62} title="订单经理 Agent" avatar={personAvatars["陈澄"]} tone="green"/>
          <Box x={24} y={272} w={166} h={62} title="研发 Agent" avatar={personAvatars["林乔"]}/><Box x={330} y={272} w={166} h={62} title="物流 Agent" avatar={personAvatars["吴桐"]}/>
          <Text x={260} y={358} small>沟通 · 交接 · 确认</Text><Text x={260} y={382} small>角色边界保留，信息交接次数没有减少</Text>
          <Box x={704} y={90} w={232} h={78} title="订单缺料 Case" tone="green"/>
          <Line d="M820 176V215M650 241V225Q650 215 660 215H980Q990 215 990 225V241" arrow="none"/>
          <Line d="M650 231V253"/><Line d="M820 215V253"/><Line d="M990 231V253"/>
          <AgentBox x={576} y={263} w={148} h={78} title="提拉 Agent" agent="path"/><AgentBox x={746} y={263} w={148} h={78} title="替代 Agent" agent="path"/><AgentBox x={916} y={263} w={148} h={78} title="拆分 Agent" agent="path"/>
          <Text x={820} y={376} small>整合计划、研发、订单、供应、物流能力</Text>
          <Text x={540} y={451}>协作的基本单元，从角色交接 → 路径求解</Text>
        </Diagram>
      </Slide>
      <Slide presentingSlide={presenting ? currentSlide : null} number={4} title="能力 vs 责任" note="这是理想化设计；信息无法全部由系统承载，实际应用中仍需由人补充 Agent 所需的信息。">
        <Diagram label="能力可以沉淀复用，责任仍由人承担。Path Agent 组合计划研发订单能力分析事实并提出方案，责任人批准否决或要求修改。人提供修改意见与补充信息，Agent 据此继续推演和修订方案。" height={438}>
          <g className="governanceDiagram">
            <text className="governanceLead" x="0" y="22">能力可以沉淀复用，责任仍由人承担</text>
            <rect className="governancePanel" x="0" y="54" width="520" height="300" rx="16"/>
            <rect className="governancePanel responsibilityPanel" x="560" y="54" width="520" height="300" rx="16"/>
            <text className="governanceSection" x="24" y="88">Agent · 分析与建议</text>
            <text className="governanceSection" x="584" y="88">人 · 确认与决策</text>
            <circle cx="66" cy="153" r="43" fill="#fff"/>
            <image href={botAvatars.path} x="27" y="110" width="78" height="86" preserveAspectRatio="xMidYMid meet"/>
            <text className="governanceHero" x="126" y="144">整合能力，生成方案</text>
            <text className="governanceHint" x="126" y="176">基于 Case 事实与探索目标开展分析</text>
            {["王淼", "林乔", "陈澄"].map((name, i) => <image key={name} href={personAvatars[name]} x={584 + i * 33} y="128" width="48" height="48" preserveAspectRatio="xMidYMid slice" style={{ clipPath: "circle(50%)" }}/>)}
            <text className="governanceHero" x="718" y="144">确认承诺，作出决策</text>
            <text className="governanceHint" x="718" y="176">专业角色 · Case Owner</text>
            <Box x={24} y={255} w={144} h={68} title="计划能力" sub="供需 · 交期"/>
            <Box x={188} y={255} w={144} h={68} title="研发能力" sub="替代 · 技术约束"/>
            <Box x={352} y={255} w={144} h={68} title="订单能力" sub="客户 · 履约影响"/>
            <Box x={584} y={255} w={144} h={68} title="批准" sub="确认方案与承诺" tone="gold"/>
            <Box x={748} y={255} w={144} h={68} title="否决" sub="说明原因与约束" tone="gold"/>
            <Box x={912} y={255} w={144} h={68} title="提出修改" sub="补充信息与意见" tone="gold"/>
            <rect className="governanceCollaboration" x="0" y="374" width="1080" height="54" rx="10"/>
            <text className="governanceSection" x="24" y="407">围绕 Case 持续协作</text>
            <text className="governanceHint" x="1056" y="407" textAnchor="end">方案与证据 / 人员反馈 / 继续推演与修订</text>
          </g>
        </Diagram>
      </Slide>
      <Slide presentingSlide={presenting ? currentSlide : null} number={5} title="三类资产：能力、规则、经验" note="平台从协作记录中自动整理角色偏好与知识，经人确认后纳入 Knowledge，供后续 Case 使用。">
        <Diagram label="将能力沉淀为 Skills，将审批责任落实为 Policies，由平台自动整理角色偏好与知识，经人确认后纳入 Knowledge，供后续 Case 使用。" height={438}>
          <g className="governanceDiagram">
            <text className="governanceLead" x="0" y="22">把人机分工，落实为可复用、可治理的平台资产</text>
            {[
              { x: 0, kind: "skills", number: "01", name: "Skills", title: "能力可复用", question: "如何分析与求解", detail: "分析方法 · 工具使用", example: "供需评估 / 替代验证", outcome: "Agent 跨角色组合调用" },
              { x: 370, kind: "policies", number: "02", name: "Policies", title: "责任有规则", question: "何时需要谁来确认", detail: "Case 类型 · Path · 审批策略", example: "确定性匹配，触发不依赖 LLM", outcome: "审批与承诺仍由人确认" },
              { x: 740, kind: "knowledge", number: "03", name: "Knowledge", title: "经验可参考", question: "理解角色偏好，积累业务知识", detail: "角色偏好 · 业务知识 · 协作经验", example: "平台自动整理，人只做确认", outcome: "为后续分析提供参考" },
            ].map(({ x, kind, number, name, title, question, detail, example, outcome }) => <g key={name} className={`assetCard asset-${kind}`}>
              <rect className="governancePanel" x={x} y="54" width="340" height="270" rx="16"/>
              <text className="assetNumber" x={x + 314} y="90" textAnchor="end">{number}</text>
              <text className="assetName" x={x + 24} y="94">{name}</text>
              <text className="assetTitle" x={x + 24} y="135">{title}</text>
              <text className="assetQuestion" x={x + 24} y="170">{question}</text>
              <path d={`M${x + 24} 188H${x + 316}`} stroke="#d3dfd3"/>
              <text className="assetDetail" x={x + 24} y="215">{detail}</text>
              <text className="assetExample" x={x + 24} y="239">{example}</text>
              <rect className="assetOutcome" x={x + 12} y="265" width="316" height="47" rx="9"/>
              <text className="assetOutcomeText" x={x + 170} y="294" textAnchor="middle">{outcome}</text>
            </g>)}
            <text className="governanceSection" x="0" y="354">知识如何沉淀</text>
            <text className="governanceHint" x="166" y="354">来源：Case 协作记录</text>
            <Line d="M268 402H296"/><Line d="M488 402H516"/><Line d="M756 402H784"/>
            <Box x={0} y={372} w={260} h={60} title="平台自动整理" sub="角色偏好与知识"/>
            <Box x={304} y={372} w={176} h={60} title="人工确认" tone="gold"/>
            <Box x={524} y={372} w={224} h={60} title="纳入 Knowledge"/>
            <Box x={792} y={372} w={288} h={60} title="后续 Case 分析" tone="green"/>
          </g>
        </Diagram>
      </Slide>
      <Slide presentingSlide={presenting ? currentSlide : null} number={6} title="三类 Agent：规划、推演、汇总">
        <Diagram label="三条 Path 并行探索审批后汇总，由 Case Owner 决策；关闭 Case 后回到最初的供应链事件，完成处置闭环" height={495} inset={24}>
          <Text x={109} y={24}>01 · 规划范围</Text>
          <Text x={528} y={24}>02 · 并行探索与审批</Text>
          <Text x={982} y={24}>03 · 汇总决策</Text>
          <path d="M244 55V455M818 55V455" stroke="#dbe4dc" strokeWidth="1"/>

          <Box x={14} y={79} w={190} h={60} title="供应链事件" icon="event"/>
          <Line d="M109 139V202"/>
          <AgentBox x={0} y={204} w={218} h={66} title="Orchestrator" agent="orchestrator"/>
          <Line d="M119 270C135 292 135 328 119 350"/><Text x={145} y={316} anchor="start" small>探索清单</Text>
          <Line d="M99 352C83 330 83 294 99 272" gold/><Text x={73} y={316} anchor="end" small>打回修改</Text>
          <Box x={14} y={352} w={190} h={60} title="Case Owner" tone="gold" icon="owner"/>
          <Line d="M204 382H226Q236 382 236 372V256Q236 246 246 246H272M272 120V372" arrow="none"/>

          {[78, 214, 350].map((y, index) => <g key={y}>
            <Line d={index === 0 ? "M272 120Q272 110 282 110H304" : index === 2 ? "M272 372Q272 382 282 382H304" : "M272 246H304"}/>
            <AgentBox x={306} y={y} w={210} h={64} title={index === 0 ? "Path Agent 1" : index === 1 ? "Path Agent 2" : "Path Agent N"} agent="path"/>
            <Text x={556} y={y+3} small>建议方案</Text><Line d={`M516 ${y+22}C538 ${y+6} 572 ${y+6} 594 ${y+22}`}/>
            <Box x={596} y={y} w={168} h={64} title="角色审批" tone="gold" icon="people"/>
            <Line d={`M596 ${y+42}C574 ${y+58} 540 ${y+58} 518 ${y+42}`} gold/>
            <Text x={556} y={y+76} small>打回修改</Text>
          </g>)}
          <Line d="M764 110H780Q790 110 790 120V372Q790 382 780 382H764M764 246H790" arrow="none"/>
          <Line d="M790 246H848Q858 246 858 236V202Q858 192 868 192H875"/>
          <circle cx="272" cy="246" r="3.5" fill="#648b7d"/><circle cx="790" cy="246" r="3.5" fill="#648b7d"/>
          <text x={824} y={223} textAnchor="middle" fontSize={13}>探索完毕</text>
          <AgentBox x={877} y={160} w={210} h={64} title="总结 Agent" agent="synthesis"/>
          <Line d="M982 224V268"/><Text x={1000} y={253} anchor="start" small>综合建议</Text>
          <Box x={887} y={270} w={190} h={60} title="Case Owner" tone="gold" icon="owner"/>
          <Line d="M790 246H848Q858 246 858 256V290Q858 300 868 300H885" gold dashed/>
          <text x="824" y="282" textAnchor="middle" fontSize="13" fill="#8b642a"><tspan x="824">审批超期</tspan></text>
          <Line d="M982 330V468Q982 480 970 480H-4Q-16 480-16 468V121Q-16 109-4 109H12"/>
          <Text x={540} y={510}>关闭 Case · 事件闭环</Text>
        </Diagram>
      </Slide>
      <Slide presentingSlide={presenting ? currentSlide : null} number={7} title="四层架构">
        <Diagram label="以 Case 为中心的四层技术架构：交互与接入、组织求解与审批、能力治理与记录、数据与运行底座。按职责分层展示平台模块。" height={444}>
          <g className="architectureDiagram">
            <text className="governanceLead" x="0" y="22">以 Case 为中心，连接交互、协作、治理与运行底座</text>
            <text className="architectureLegend" x="1080" y="22" textAnchor="end">按职责分层</text>
            {[
              { y: 52, number: "01", label: "交互与接入", sub: "呈现信息 · 接收操作", items: [["React 工作台", "Case · 待办 · 资产 · Trace", "monitor"], ["FastAPI", "HTTP API · 请求与响应", "api"]] },
              { y: 152, number: "02", label: "组织求解与审批", sub: "Agent 提议 · 人员决策", items: [["Orchestrator", "规划探索清单", "orchestrator"], ["Path / Synthesis Agent", "并行推演 · 汇总建议", "path"], ["人员审批与决策", "专业角色 · Case Owner", "people"]] },
              { y: 252, number: "03", label: "能力治理与记录", sub: "约束行为 · 留存证据", items: [["CapabilityRegistry", "Skills · Policies · Knowledge", "layers"], ["CaseService", "状态机 · 权限 · 承诺依赖", "shield"], ["CaseRepository", "业务事件 · 版本 · 运行轨迹", "archive"]] },
              { y: 352, number: "04", label: "数据与运行底座", sub: "持久存储 · 模型执行", items: [["SQLite", "Case JSON · Events · Traces", "database"], ["版本化目录文件", "能力资产 · Path 目录", "folder"], ["Agent Runtime / Adapter", "模型调用 · 重试 · 只读工具", "cpu"]] },
            ].map(({ y, number, label, sub, items }) => <g key={number} className={`architectureLayer${number === "02" ? " architectureLayerCore" : ""}`}>
              <rect className="architectureLayerSurface" x="0" y={y} width="1080" height="86" rx="13"/>
              <rect className="architectureLayerLabel" x="0" y={y} width="224" height="86" rx="13"/>
              <rect className="architectureLayerIconBadge" x="16" y={y + 21} width="42" height="42" rx="11"/>
              <g className="architectureLayerIcon"><ArchitectureIcon name={["monitor", "workflow", "shield", "database"][Number(number) - 1]} x={24} y={y + 29}/></g>
              <text className="architectureLayerNumber" x="209" y={y + 17} textAnchor="end">{number}</text>
              <text className="architectureLayerTitle" x="70" y={y + 35}>{label}</text>
              <text className="architectureLayerSub" x="70" y={y + 60}>{sub}</text>
              {items.map(([title, desc, icon], i) => {
                const width = items.length === 2 ? 400 : 262;
                const x = 244 + i * (width + 16);
                return <g key={title}>
                  <rect className="architectureModule" x={x} y={y + 10} width={width} height="66" rx="9"/>
                  <rect className={`architectureModuleIconBadge architectureIcon-${icon}`} x={x + 12} y={y + 25} width="36" height="36" rx="9"/>
                  {icon === "orchestrator" || icon === "path" ? <image href={botAvatars[icon]} x={x + 12} y={y + 22} width="36" height="42" preserveAspectRatio="xMidYMid meet"/> : <g className="architectureModuleIcon"><ArchitectureIcon name={icon} x={x + 18} y={y + 31} size={24}/></g>}
                  <text className="architectureModuleTitle" x={x + 60} y={y + 36}>{title}</text>
                  <text className="architectureModuleSub" x={x + 60} y={y + 58}>{desc}</text>
                </g>;
              })}
              {number !== "04" && <path className="architectureLayerConnector" d={`M111 ${y + 89}v8m-4-4 4 4 4-4`}/>}
            </g>)}
          </g>
        </Diagram>
      </Slide>
    </main>
    {presenting && <nav className="aboutPlayback" aria-label="幻灯片播放控制">
      <button type="button" disabled={currentSlide === 1} onClick={() => moveSlide(-1)}>← 上一页</button>
      <span aria-live="polite">{currentSlide} / {chapters.length}</span>
      <button type="button" disabled={currentSlide === chapters.length} onClick={() => moveSlide(1)}>下一页 →</button>
      <button type="button" onClick={stopPresentation}>退出全屏</button>
    </nav>}
  </div>;
}
