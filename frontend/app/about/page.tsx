"use client";

import Link from "next/link";
import { useId, type ReactNode } from "react";
import { botAvatars } from "../lib/identities";
import "./about.css";

const chapters = ["流程与 Case", "角色与求解", "能力与责任", "Case 工作流", "平台资产", "技术架构"];

function Slide({ number, title, children, note }: { number: number; title: string; children: ReactNode; note?: string }) {
  return <section className="aboutSlide" id={`slide-${number}`} aria-labelledby={`heading-${number}`}>
    <div className="aboutSlideBody">
      {number === 1 ? <h1 id={`heading-${number}`}>{title}</h1> : <h2 id={`heading-${number}`}>{title}</h2>}
      {children}
      {note && <p className={`aboutNote${number === 3 ? " aboutNoteEmphasis" : ""}`}>{note}</p>}
    </div>
    <footer className="aboutSlideFooter"><span>{String(number).padStart(2, "0")} / 06</span></footer>
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

function Box({ x, y, w = 160, h = 62, title, sub, tone = "plain", icon }: { x: number; y: number; w?: number; h?: number; title: string; sub?: string; tone?: "plain" | "green" | "gold"; icon?: "event" | "people" | "owner" }) {
  return <g className={`diagramBox ${tone}`}><rect x={x} y={y} width={w} height={h} rx="9"/>{icon && <NodeIcon name={icon} x={x + 15} y={y + h / 2 - 18}/>}<text x={x + w / 2 + (icon ? 23 : 0)} y={y + h / 2 + (sub ? -8 : 1)} dominantBaseline="middle" textAnchor="middle" className="boxTitle">{title}</text>{sub && <text x={x + w / 2 + (icon ? 23 : 0)} y={y + h / 2 + 19} textAnchor="middle" className="boxSub">{sub}</text>}</g>;
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
  return <div className="aboutPage">
    <div className="aboutToolbar"><Link href="/">← 返回工作台</Link><span>关于 Agentic CM · 6 页演示</span><button type="button" onClick={() => window.print()}>导出 PDF slides ↗</button></div>
    <div className="aboutGuide"><span>导出时选择「另存为 PDF」，关闭页眉和页脚</span><nav aria-label="About 章节">{chapters.map((chapter, index) => <a key={chapter} href={`#slide-${index + 1}`}>{String(index + 1).padStart(2, "0")} {chapter}</a>)}</nav></div>
    <main className="aboutDeck">
      <Slide number={1} title="业务流程 vs 事件驱动">
        <Diagram label="业务流程按确定节点流转，Case 管理围绕目标探索未知路径；关闭 Case 需要主计划、研发、订单经理等多角色沟通、确认方案与承诺，再由 Case Owner 决策闭环" height={465}>
          <rect className="diagramPanel" x="0" y="0" width="510" height="310" rx="14"/><rect className="diagramPanel" x="540" y="0" width="540" height="310" rx="14"/>
          <Text x={255} y={45}>Business Process · 确定性流转</Text>
          <Box x={24} y={128} w={126} h={80} title="节点 A" sub="接收订单"/><Box x={192} y={128} w={126} h={80} title="节点 B" sub="核验条件"/><Box x={360} y={128} w={126} h={80} title="节点 C" sub="批准执行"/>
          <Line d="M156 168H184"/><Line d="M324 168H352"/>
          <Text x={255} y={273} small>规则已知，按预定义节点推进</Text>
          <Text x={810} y={45}>Case Management · 目标驱动</Text>
          <Box x={562} y={128} w={110} h={80} title="事件"/><Box x={941} y={128} w={105} h={80} title="目标" tone="green"/>
          <Line d="M678 151C710 151 706 94 740 94" dashed/><Line d="M678 168H740" dashed/><Line d="M678 185C710 185 706 242 740 242" dashed/>
          <Box x={748} y={69} w={118} h={50} title="路径 A ?"/><Box x={748} y={143} w={118} h={50} title="路径 B ?"/><Box x={748} y={217} w={118} h={50} title="新路径 ?"/>
          <Line d="M872 94C898 94 889 151 933 151" dashed/><Line d="M872 168H933" dashed/><Line d="M872 242C898 242 889 185 933 185" dashed/>
          <Text x={810} y={289} small>目标明确，路径需多角色沟通与共同判断</Text>
          <Line d="M255 316V329Q255 339 265 339H800Q810 339 810 329V316" arrow="none"/>
          <Line d="M540 339V361"/>
          <Box x={0} y={371} w={1080} h={90} title="关闭 Case：多角色沟通 → 方案与承诺确认 → Case Owner 决策闭环" tone="green"/>
        </Diagram>
      </Slide>
      <Slide number={2} title="按人拆 vs 按路径拆">
        <Diagram label="角色数字分身以订单经理为中心，与主计划、研发、供应经理和物流构成协作网络，仍需沟通交接确认；按提拉、替代等问题组织 Agent，可以跨学科整合求解" height={465}>
          <rect className="diagramPanel" x="0" y="0" width="520" height="399" rx="14"/><rect className="diagramPanel" x="560" y="0" width="520" height="399" rx="14"/>
          <Text x={260} y={45}>按角色复制数字分身</Text><Text x={820} y={45}>按问题组织求解 Agent</Text>
          <Line d="M198 111H322" arrow="both" dashed/><Line d="M198 303H322" arrow="both" dashed/>
          <Line d="M107 148V266" arrow="both" dashed/><Line d="M413 148V266" arrow="both" dashed/>
          <Line d="M150 148L207 168" arrow="both"/><Line d="M370 148L313 168" arrow="both"/>
          <Line d="M150 266L207 246" arrow="both"/><Line d="M370 266L313 246" arrow="both"/>
          <Box x={24} y={80} w={166} h={62} title="主计划 Agent"/><Box x={330} y={80} w={166} h={62} title="供应经理 Agent"/>
          <Box x={165} y={176} w={190} h={62} title="订单经理 Agent" tone="green"/>
          <Box x={24} y={272} w={166} h={62} title="研发 Agent"/><Box x={330} y={272} w={166} h={62} title="物流 Agent"/>
          <Text x={260} y={358} small>沟通 · 交接 · 确认</Text><Text x={260} y={382} small>角色边界保留，信息交接次数没有减少</Text>
          <Box x={704} y={90} w={232} h={78} title="订单缺料 Case" tone="green"/>
          <Line d="M820 176V215M650 241V225Q650 215 660 215H980Q990 215 990 225V241" arrow="none"/>
          <Line d="M650 231V253"/><Line d="M820 215V253"/><Line d="M990 231V253"/>
          <Box x={576} y={263} w={148} h={78} title="提拉 Agent"/><Box x={746} y={263} w={148} h={78} title="替代 Agent"/><Box x={916} y={263} w={148} h={78} title="拆分 Agent"/>
          <Text x={820} y={376} small>整合计划、研发、订单、供应、物流能力</Text>
          <Text x={540} y={451}>协作的基本单元，从角色交接 → 路径求解</Text>
        </Diagram>
      </Slide>
      <Slide number={3} title="能力 vs 责任" note="备注：这是理想化设计，信息无法全部在系统中承载；实际应用中，人还需在 Agent 提问时补充信息。">
        <Diagram label="人员能力沉淀为跨角色 Skills，Path Agent 整合并生成方案；人负责批准否决或提出修改意见，所有记录归入 Case" height={448}>
          <rect className="diagramPanel" x="0" y="0" width="300" height="338" rx="14"/>
          <Text x={150} y={38}>人的能力 → 可以抽取</Text><Text x={950} y={106}>人的责任 → 仍然存在</Text>
          <Box x={22} y={66} w={256} h={66} title="计划能力 · 供需与交期"/><Box x={22} y={154} w={256} h={66} title="研发能力 · 替代可行性"/><Box x={22} y={242} w={256} h={66} title="订单能力 · 客户与履约"/>
          <Line d="M284 99H316Q326 99 326 109V265Q326 275 316 275H284M284 187H326" arrow="none"/>
          <Line d="M326 187H362"/>
          <AgentBox x={372} y={138} w={250} h={98} title="Path Agent" sub="跨角色整合分析" agent="path"/>
          <Text x={497} y={78} small>Case 事实 + 探索目标</Text><Line d="M497 91V128"/>
          <Text x={719} y={169} small>建议方案</Text><Line d="M630 187H812"/><Text x={719} y={213} small>证据与风险</Text>
          <Box x={822} y={138} w={258} h={98} title="相关责任人" sub="批准 / 否决 / 修改意见" tone="gold" icon="people"/>
          <Line d="M951 246V292Q951 304 939 304H509Q497 304 497 292V246" gold/><Text x={710} y={289} small>修改意见</Text>
          <Box x={0} y={382} w={1080} h={60} title="Case 统一记录与审计：事实 → 方案版本 → 人员意见 → 承诺与决策" tone="green"/>
        </Diagram>
      </Slide>
      <Slide number={4} title="三类 Agent：规划、推演、汇总">
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
      <Slide number={5} title="三类资产：能力、规则、经验" note="演进方式：角色意见与经验经人工整理后纳入 Knowledge，供后续 Case 参考；当前不做自动学习或自动回写。">
        <Diagram label="Skills 是可复用能力，Policies 通过确定性规则触发审批，Knowledge 保存观察记忆经验；Case 意见经验经整理沉淀供下次分析参考" height={450}>
          <rect className="diagramPanel" x="0" y="0" width="340" height="300" rx="14"/><rect className="diagramPanel" x="370" y="0" width="340" height="300" rx="14"/><rect className="diagramPanel" x="740" y="0" width="340" height="300" rx="14"/>
          <Text x={170} y={43}>Skills · 可复用的能力</Text><Text x={540} y={43}>Policies · 审批策略</Text><Text x={910} y={43}>Knowledge · 观察、记忆、经验</Text>
          <Box x={25} y={86} w={290} h={70} title="分析方法 + 工具使用"/><Line d="M170 165V194"/><Box x={25} y={204} w={290} h={70} title="Agent 跨角色组合调用" tone="green"/>
          <Box x={395} y={86} w={290} h={70} title="Case 类型 + Path"/><Line d="M540 165V194"/><Box x={395} y={204} w={290} h={70} title="确定性匹配 → 审批责任" tone="gold"/>
          <Box x={765} y={86} w={290} h={70} title="角色意见 + 既往经验"/><Line d="M910 165V194"/><Box x={765} y={204} w={290} h={70} title="供 Agent 参考与判断" tone="green"/>
          <Text x={540} y={339}>触发不依赖 LLM</Text>
          <Box x={0} y={377} w={248} h={67} title="本次 Case 意见与经验"/><Line d="M256 410H282"/><Box x={292} y={377} w={220} h={67} title="沉淀与人工确认"/><Line d="M520 410H546"/><Box x={556} y={377} w={220} h={67} title="Knowledge"/><Line d="M784 410H810"/><Box x={820} y={377} w={260} h={67} title="下一次 Case 的分析" tone="green"/>
        </Diagram>
      </Slide>
      <Slide number={6} title="四层架构">
        <Diagram label="四层技术架构：交互与接入层，组织求解审批层，能力治理记录底座，数据与基础设施层" height={456}>
          {[
            { y: 0, label: "交互与接入", sub: "呈现与入口", tone: "plain" as const, items: [["React 工作台", "Case · 待办 · 资产 · Trace"], ["FastAPI", "HTTP API · 请求与响应"]] },
            { y: 119, label: "组织 · 求解 · 审批", sub: "协作与决策", tone: "green" as const, items: [["Orchestrator", "规划探索清单"], ["Path / Synthesis Agent", "并行推演 · 总结建议"], ["人员审批与决策", "专业角色 · Case Owner"]] },
            { y: 238, label: "能力 · 治理 · 记录", sub: "平台底座", tone: "plain" as const, items: [["CapabilityRegistry", "Skills · Policies · Knowledge"], ["CaseService", "状态机 · 权限 · 承诺依赖"], ["CaseRepository", "业务事件 · 版本 · 运行轨迹"]] },
            { y: 357, label: "数据与基础设施", sub: "存储与运行", tone: "plain" as const, items: [["SQLite", "Case JSON · Events · Traces"], ["版本化目录文件", "能力资产 · Path 目录"], ["Agent Runtime / Adapter", "模型调用 · 重试 · 只读工具"]] },
          ].map(({y,label,sub,tone,items}) => <g key={label}><rect className="diagramPanel" x="0" y={y} width="1080" height="96" rx="12"/><Text x={122} y={y+40}>{label}</Text><Text x={122} y={y+68} small>{sub}</Text>{items.map(([title,desc],i) => <Box key={title} x={260+i*(800/items.length)} y={y+11} w={800/items.length-12} h={74} title={title} sub={desc} tone={tone}/>)}{y<357 && <Line d={`M661 ${y+101}V${y+113}`}/>}</g>)}
        </Diagram>
      </Slide>
    </main>
  </div>;
}
