"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Brain, Network, BarChart3, Cpu } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "总览大盘", icon: Activity, badge: "实时" },
  { href: "/reasoning", label: "双系统推理", icon: Brain, badge: "Tool" },
  { href: "/graph", label: "知识图谱", icon: Network, badge: "Neo4j" },
  { href: "/metrics", label: "实验对比", icon: BarChart3, badge: "RQ" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 border-r border-[var(--border)] bg-white flex flex-col">
      <div className="p-6 border-b border-[var(--border)]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-emerald-500 flex items-center justify-center shadow-sm">
            <Cpu className="w-5 h-5 text-white" strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="text-sm font-bold text-zinc-900">AIOps Agent</h1>
            <p className="text-xs text-zinc-500">双过程认知运维</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center justify-between px-3 py-2.5 rounded-md text-sm transition-all",
                isActive
                  ? "bg-[var(--primary-soft)] text-[var(--primary)] font-medium"
                  : "text-zinc-600 hover:bg-zinc-50 hover:text-zinc-900"
              )}
            >
              <div className="flex items-center gap-3">
                <Icon className="w-4 h-4" />
                <span>{item.label}</span>
              </div>
              {item.badge && (
                <span className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded font-mono",
                  isActive ? "bg-blue-100 text-blue-700" : "bg-zinc-100 text-zinc-600"
                )}>
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-[var(--border)] text-xs space-y-1.5">
        <div className="flex justify-between items-center">
          <span className="text-zinc-500">K3s Cluster</span>
          <span className="text-[var(--success)] font-mono flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--success)] status-glow"></span>
            Ready
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">微服务</span>
          <span className="font-mono text-zinc-900">20/20</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">Qwen2.5 7B</span>
          <span className="font-mono text-[var(--accent)]">INT4 / 4.2GB</span>
        </div>
        <div className="flex justify-between">
          <span className="text-zinc-500">诊断模式</span>
          <span className="font-mono text-[var(--primary)]">GraphRAG</span>
        </div>
      </div>
    </aside>
  );
}
