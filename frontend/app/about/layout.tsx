import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "关于项目 · Agentic Case Management",
  description: "项目解决的问题、协作流程、实际架构与核心组件；支持导出 16:9 PDF slides。",
};

export default function AboutLayout({ children }: { children: React.ReactNode }) {
  return children;
}
