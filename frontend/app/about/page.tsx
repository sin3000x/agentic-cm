"use client";

import Link from "next/link";
import { useId, type ReactNode } from "react";
import "./about.css";

const chapters = ["流程与 Case", "角色与求解", "能力与责任", "Case 工作流", "平台资产", "技术架构"];

function Slide({ number, title, children, note }: { number: number; title: string; children: ReactNode; note?: string }) {
  return <section className="aboutSlide" id={`slide-${number}`} aria-labelledby={`heading-${number}`}>
    <div className="aboutSlideBody">
      {number === 1 ? <h1 id={`heading-${number}`}>{title}</h1> : <h2 id={`heading-${number}`}>{title}</h2>}
      {children}
      {note && <p className="aboutNote">{note}</p>}
    </div>
    <footer className="aboutSlideFooter"><span>{String(number).padStart(2, "0")} / 06</span></footer>
  </section>;
}

function Diagram({ label, children, height = 360 }: { label: string; children: ReactNode; height?: number }) {
  const id = useId().replace(/:/g, "");
  // A scrollable diagram needs keyboard focus so arrow keys can pan it on narrow screens.
  // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
  return <div className="aboutDiagramScroll" tabIndex={0} role="region" aria-label={label}><svg className="aboutDiagram" viewBox={`0 0 1080 ${height}`} role="img" aria-labelledby={id}><title id={id}>{label}</title>{children}</svg></div>;
}
function Box({ x, y, w = 160, h = 62, title, sub, tone = "plain" }: { x: number; y: number; w?: number; h?: number; title: string; sub?: string; tone?: "plain" | "green" | "gold" }) {
  return <g className={`diagramBox ${tone}`}><rect x={x} y={y} width={w} height={h} rx="9"/><text x={x + w / 2} y={y + h / 2 + (sub ? -8 : 1)} dominantBaseline="middle" textAnchor="middle" className="boxTitle">{title}</text>{sub && <text x={x + w / 2} y={y + h / 2 + 19} textAnchor="middle" className="boxSub">{sub}</text>}</g>;
}
function Line({ d, dashed = false, gold = false, arrow = "end" }: { d: string; dashed?: boolean; gold?: boolean; arrow?: "end" | "both" | "none" }) {
  const id = useId().replace(/:/g, "");
  const color = gold ? "#a57730" : "#648b7d";
  return <g><defs><marker id={id} markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto-start-reverse"><path d="M0 0 9 4.5 0 9Z" fill={color}/></marker></defs><path d={d} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" strokeDasharray={dashed ? "6 5" : undefined} markerStart={arrow === "both" ? `url(#${id})` : undefined} markerEnd={arrow !== "none" ? `url(#${id})` : undefined}/></g>;
}
function Text({ x, y, children, small = false, anchor = "middle" }: { x: number; y: number; children: ReactNode; small?: boolean; anchor?: "start" | "middle" }) {
  return <text x={x} y={y} textAnchor={anchor} className={small ? "diagramSmall" : "diagramText"}>{children}</text>;
}

export default function AboutPage() {
  return <div className="aboutPage">
    <div className="aboutToolbar"><Link href="/">← 返回工作台</Link><span>关于 Agentic CM · 6 页演示</span><button type="button" onClick={() => window.print()}>导出 PDF slides ↗</button></div>
    <div className="aboutGuide"><span>导出时选择「另存为 PDF」，关闭页眉和页脚</span><nav aria-label="About 章节">{chapters.map((chapter, index) => <a key={chapter} href={`#slide-${index + 1}`}>{String(index + 1).padStart(2, "0")} {chapter}</a>)}</nav></div>
    <main className="aboutDeck">
      <Slide number={1} title="业务流程 vs 事件驱动">
        <Diagram label="业务流程按确定节点流转，Case 管理围绕目标探索未知路径；供应链事件以 Case 组织探索，以 Policy 固化审批" height={465}>
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
          <Text x={810} y={289} small>目标明确，路径随事实与判断展开</Text>
          <Line d="M255 316V329Q255 339 265 339H800Q810 339 810 329V316" arrow="none"/>
          <Line d="M540 339V361"/>
          <Box x={0} y={371} w={1080} h={90} title="供应链事件 → Case 组织探索 + Policy 固化审批" sub="订单延期 · 提拉 / 替代 / 拆分等路径探索 · 按规则由责任人确认" tone="green"/>
        </Diagram>
      </Slide>
      <Slide number={2} title="按人拆分 vs 按路径拆分">
        <Diagram label="角色数字分身仍在主计划、研发和订单经理之间交接；按提拉、替代等问题组织 Agent，可以跨学科整合求解" height={465}>
          <rect className="diagramPanel" x="0" y="0" width="520" height="399" rx="14"/><rect className="diagramPanel" x="560" y="0" width="520" height="399" rx="14"/>
          <Text x={260} y={45}>按角色复制数字分身</Text><Text x={820} y={45}>按问题组织求解 Agent</Text>
          <Box x={176} y={90} w={168} h={78} title="主计划 Agent"/><Box x={24} y={263} w={166} h={78} title="研发 Agent"/><Box x={326} y={263} w={170} h={78} title="订单经理 Agent"/>
          <Line d="M189 176L117 254" arrow="both"/><Line d="M332 176L404 254" arrow="both"/><Line d="M199 302H317" arrow="both"/>
          <Text x={260} y={227} small>沟通 · 交接 · 确认</Text><Text x={260} y={376} small>角色边界保留，信息交接次数没有减少</Text>
          <Box x={704} y={90} w={232} h={78} title="一个供应链 Case" tone="green"/>
          <Line d="M820 176V215M650 241V225Q650 215 660 215H980Q990 215 990 225V241" arrow="none"/>
          <Line d="M650 231V253"/><Line d="M820 215V253"/><Line d="M990 231V253"/>
          <Box x={576} y={263} w={148} h={78} title="提拉 Agent"/><Box x={746} y={263} w={148} h={78} title="替代 Agent"/><Box x={916} y={263} w={148} h={78} title="拆分 Agent"/>
          <Text x={820} y={376} small>整合计划、研发、订单等跨学科能力</Text>
          <Text x={540} y={451}>协作的基本单元，从“角色之间交接”转向“围绕路径求解”</Text>
        </Diagram>
      </Slide>
      <Slide number={3} title="能力可以复用，但需要人担责" note="备注：这是理想化设计，信息无法全部在系统中承载；实际应用中，人还需在 Agent 提问时补充信息。">
        <Diagram label="人员能力沉淀为跨角色 Skills，Path Agent 整合并生成方案；人负责批准否决或提出修改意见，所有记录归入 Case" height={448}>
          <rect className="diagramPanel" x="0" y="0" width="300" height="338" rx="14"/>
          <Text x={150} y={38}>人的能力 → 可以抽取</Text><Text x={950} y={106}>人的责任 → 仍然存在</Text>
          <Box x={22} y={66} w={256} h={66} title="计划能力 · 供需与交期"/><Box x={22} y={154} w={256} h={66} title="研发能力 · 替代可行性"/><Box x={22} y={242} w={256} h={66} title="订单能力 · 客户与履约"/>
          <Line d="M284 99H316Q326 99 326 109V265Q326 275 316 275H284M284 187H326" arrow="none"/>
          <Line d="M326 187H362"/>
          <Box x={372} y={138} w={192} h={98} title="Path Agent" sub="跨角色整合分析" tone="green"/>
          <Text x={468} y={78} small>Case 事实 + 探索目标</Text><Line d="M468 91V128"/>
          <Line d="M572 187H606"/><Box x={616} y={148} w={154} h={78} title="建议方案" sub="证据与风险"/>
          <Line d="M778 187H812"/><Box x={822} y={138} w={258} h={98} title="相关责任人" sub="批准 / 否决 / 修改意见" tone="gold"/>
          <Line d="M951 246V292Q951 304 939 304H480Q468 304 468 292V246" gold/><Text x={710} y={289} small>修改意见</Text>
          <Box x={0} y={382} w={1080} h={60} title="Case 统一记录与审计：事实 → 方案版本 → 人员意见 → 承诺与决策" tone="green"/>
        </Diagram>
      </Slide>
      <Slide number={4} title="围绕 Case 并行探索，在人的判断中闭环" note="设计说明：虚线为待实现的超期升级；当前 Demo 在各 Path 通过或否决后汇总，外部后续动作由人执行。">
        <Diagram label="事件经 Orchestrator 形成探索清单，Owner 微调并启动并行路径；每条路径生成方案并审批，支持修改循环；通过后总结并交 Owner，超期则升级 Owner" height={480}>
          <Box x={0} y={0} w={146} h={76} title="供应链事件" sub="生成 Case"/>
          <Line d="M154 38H180"/>
          <Box x={190} y={0} w={254} h={76} title="Orchestrator" sub="理解事件 · 整合平台能力" tone="green"/>
          <Line d="M452 38H478"/><Box x={488} y={0} w={192} h={76} title="探索清单" sub="路径与能力组合"/>
          <Line d="M688 38H714"/><Box x={724} y={0} w={356} h={76} title="Case Owner" sub="微调 Path · 启动探索" tone="gold"/>
          <Line d="M902 84V97Q902 107 892 107H27Q17 107 17 117V324" arrow="none"/>
          <Text x={352} y={143} small>获批路径并行探索 · 可扩展更多 Path</Text>
          {[165, 289].map((y, index) => <g key={y}>
            <Line d={`M17 ${y+36}H44`}/><Box x={54} y={y} w={206} h={72} title={index === 0 ? "提拉 Path Agent" : "替代 Path Agent"} sub="按探索清单推演" tone="green"/>
            <Line d={`M268 ${y+36}H299`}/><Box x={309} y={y} w={139} h={72} title="建议方案"/>
            <Line d={`M456 ${y+36}H487`}/><Box x={497} y={y} w={195} h={72} title="相关角色审批" sub="Policy 确定责任人" tone="gold"/>
            <Line d={`M594 ${y+79}V${y+93}Q594 ${y+103} 584 ${y+103}H167Q157 ${y+103} 157 ${y+93}V${y+80}`} gold/><Text x={378} y={y+96} small>打回修改 · 重新推演</Text>
          </g>)}
          <Line d="M700 201H730Q740 201 740 211V315Q740 325 730 325H700" arrow="none"/>
          <Line d="M740 257H778"/>
          <Text x={934} y={182} small>全部通过后汇合</Text><Box x={788} y={205} w={292} h={93} title="总结 Agent" sub="比较结果 · 给出建议" tone="green"/>
          <Line d="M934 306V329"/><Box x={788} y={339} w={292} h={81} title="Case Owner" sub="后续动作 · 完成闭环" tone="gold"/>
          <Line d="M700 336H717Q727 336 727 346V437Q727 447 737 447H984Q994 447 994 437V428" dashed gold/><Text x={899} y={471} small>审批超期 · 直接升级 Owner</Text>
        </Diagram>
      </Slide>
      <Slide number={5} title="三类资产，让能力可复用、规则可执行、经验可积累" note="演进方式：角色意见与经验经人工整理后纳入 Knowledge，供后续 Case 参考；当前不做自动学习或自动回写。">
        <Diagram label="Skills 是可复用能力，Policies 通过确定性规则触发审批，Knowledge 保存观察记忆经验；Case 意见经验经整理沉淀供下次分析参考" height={450}>
          <rect className="diagramPanel" x="0" y="0" width="340" height="300" rx="14"/><rect className="diagramPanel" x="370" y="0" width="340" height="300" rx="14"/><rect className="diagramPanel" x="740" y="0" width="340" height="300" rx="14"/>
          <Text x={170} y={43}>Skills · 可复用的能力</Text><Text x={540} y={43}>Policies · 审批策略</Text><Text x={910} y={43}>Knowledge · 观察、记忆、经验</Text>
          <Box x={25} y={86} w={290} h={70} title="分析方法 + 工具使用"/><Line d="M170 165V194"/><Box x={25} y={204} w={290} h={70} title="Agent 跨角色组合调用" tone="green"/>
          <Box x={395} y={86} w={290} h={70} title="Case 类型 + Path"/><Line d="M540 165V194"/><Box x={395} y={204} w={290} h={70} title="确定性匹配 → 审批责任" tone="gold"/>
          <Box x={765} y={86} w={290} h={70} title="角色意见 + 既往经验"/><Line d="M910 165V194"/><Box x={765} y={204} w={290} h={70} title="供 Agent 参考与判断" tone="green"/>
          <Text x={540} y={339}>Policy 的触发不交给 LLM 决策</Text>
          <Box x={0} y={377} w={248} h={67} title="本次 Case 意见与经验"/><Line d="M256 410H282"/><Box x={292} y={377} w={220} h={67} title="人工整理与沉淀"/><Line d="M520 410H546"/><Box x={556} y={377} w={220} h={67} title="Knowledge"/><Line d="M784 410H810"/><Box x={820} y={377} w={260} h={67} title="下一次 Case 的分析" tone="green"/>
        </Diagram>
      </Slide>
      <Slide number={6} title="四层架构，支撑同一个 Case 的完整生命周期">
        <Diagram label="四层技术架构：交互与接入层，组织求解审批层，能力治理记录底座，数据与基础设施层" height={456}>
          {[
            { y: 0, label: "交互与接入", sub: "呈现与入口", tone: "plain" as const, items: [["React 工作台", "Case · 待办 · 资产 · Trace"], ["FastAPI", "HTTP API · 请求与响应"]] },
            { y: 119, label: "组织 · 求解 · 审批", sub: "协作与决策", tone: "green" as const, items: [["Orchestrator", "规划探索清单"], ["Path / Synthesis Agent", "并行推演 · 总结建议"], ["人员审批与决策", "专业角色 · Case Owner"]] },
            { y: 238, label: "能力 · 治理 · 记录", sub: "平台底座", tone: "plain" as const, items: [["CapabilityRegistry", "Skills · Policies · Knowledge"], ["CaseService", "状态机 · 权限 · 承诺依赖"], ["CaseRepository", "业务事件 · 版本 · 运行轨迹"]] },
            { y: 357, label: "数据与基础设施", sub: "存储与运行", tone: "plain" as const, items: [["SQLite", "Case JSON · Events · Traces"], ["版本化目录文件", "能力资产 · Path 目录"], ["Agent Runtime / Adapter", "模型调用 · 重试 · 只读工具"]] },
          ].map(({y,label,sub,tone,items}) => <g key={label}><rect className="diagramPanel" x="0" y={y} width="1080" height="96" rx="12"/><Text x={122} y={y+40}>{label}</Text><Text x={122} y={y+68} small>{sub}</Text>{items.map(([title,desc],i) => <Box key={title} x={260+i*(800/items.length)} y={y+11} w={800/items.length-12} h={74} title={title} sub={desc} tone={tone}/>)}{y<357 && <Line d={`M661 ${y+101}V${y+113}`}/>}</g>)}
        </Diagram>
        <p className="aboutArchitectureCaption">逻辑分层对应当前模块，后端在同一 Python 进程内运行</p>
      </Slide>
    </main>
  </div>;
}
