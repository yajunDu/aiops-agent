"use client";

import { ReasoningStep } from "@/lib/mock-data";
import { cn } from "@/lib/utils";
import {
  Activity, Brain, Wrench, Database, CheckCircle2,
  Terminal, Sparkles,
} from "lucide-react";

const PHASE_CONFIG = {
  system1: {
    label: "系统 1",
    sublabel: "快系统",
    color: "text-blue-700",
    bg: "bg-blue-100",
    border: "border-blue-300",
    ring: "ring-blue-400",
    accent: "bg-blue-600",
  },
  system2: {
    label: "系统 2",
    sublabel: "慢系统",
    color: "text-emerald-700",
    bg: "bg-emerald-100",
    border: "border-emerald-300",
    ring: "ring-emerald-400",
    accent: "bg-emerald-600",
  },
  execution: {
    label: "执行层",
    sublabel: "干预",
    color: "text-amber-700",
    bg: "bg-amber-100",
    border: "border-amber-300",
    ring: "ring-amber-400",
    accent: "bg-amber-600",
  },
};

const TYPE_ICONS = {
  anomaly_slice: Activity,
  thought: Brain,
  tool_call: Wrench,
  cypher: Database,
  result: CheckCircle2,
  sop: Terminal,
};

interface Props {
  step: ReasoningStep;
  isActive?: boolean;
  isCompleted?: boolean;
}

export default function ReasoningStepCard({ step, isActive, isCompleted }: Props) {
  const config = PHASE_CONFIG[step.phase];
  const Icon = TYPE_ICONS[step.type];
  const isCode = step.type === "cypher" || step.type === "sop" || step.type === "result";

  return (
    <div className={cn(
      "relative pl-12 pb-6 transition-all",
      !isCompleted && !isActive && "opacity-50"
    )}>
      {/* 时间线竖线 */}
      <div className="absolute left-4 top-9 bottom-0 w-px bg-zinc-200" />

      {/* 时间线节点 */}
      <div className={cn(
        "absolute left-0 top-0.5 w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all bg-white",
        config.border,
        isActive && cn("ring-2 ring-offset-2", config.ring, "status-glow")
      )}>
        <Icon className={cn("w-4 h-4", config.color)} strokeWidth={2.2} />
      </div>

      {/* 内容卡片 */}
      <div className={cn(
        "rounded-lg border bg-white transition-all shadow-sm",
        isActive ? "border-blue-300 shadow-md" : "border-zinc-200"
      )}>
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-zinc-200">
          <div className="flex items-center gap-2.5">
            <span className={cn(
              "text-[10px] font-mono px-2 py-0.5 rounded font-semibold uppercase tracking-wider",
              config.bg, config.color
            )}>
              {config.label}
            </span>
            <span className="text-sm font-semibold text-zinc-900">{step.title}</span>
            {isActive && <Sparkles className="w-3.5 h-3.5 text-blue-500 status-glow" />}
          </div>
          {step.duration_ms !== undefined && (
            <span className="text-[10px] font-mono text-zinc-500">
              {step.duration_ms} ms
            </span>
          )}
        </div>
        <div className="p-4">
          {isCode ? (
            <pre className={cn(
              "text-xs font-mono whitespace-pre-wrap leading-relaxed rounded-md p-3 overflow-x-auto",
              step.type === "cypher" ? "bg-emerald-50 text-emerald-900 border border-emerald-200" :
              step.type === "sop" ? "bg-zinc-900 text-zinc-100" :
              "bg-zinc-50 text-zinc-800 border border-zinc-200"
            )}>
              {step.content}
            </pre>
          ) : (
            <p className="text-sm text-zinc-700 leading-relaxed whitespace-pre-wrap">
              {step.content}
            </p>
          )}

          {step.metadata && (
            <div className="mt-3 pt-3 border-t border-zinc-200 grid grid-cols-3 gap-3">
              {Object.entries(step.metadata).map(([key, value]) => (
                <div key={key}>
                  <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5 font-medium">{key}</p>
                  <p className="text-xs font-mono text-zinc-900 font-medium">{value}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
