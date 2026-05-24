"use client";

import { useEffect, useState } from "react";
import { BarChart3, Loader2 } from "lucide-react";
import { api, type BaselineMethod, type FaultTypeStat } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function MetricsPage() {
  const [data, setData] = useState<{ methods: BaselineMethod[]; fault_types: FaultTypeStat[] } | null>(null);
  
  useEffect(() => { api.baselines().then(setData).catch(console.error); }, []);

  if (!data) return <div className="p-6 flex items-center text-zinc-500"><Loader2 className="w-4 h-4 animate-spin mr-2"/>加载中...</div>;

  const maxVal = 100;

  return (
    <div className="p-6 space-y-6 max-w-[1600px]">
      <header className="flex items-center gap-2">
        <BarChart3 className="w-5 h-5 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">实验对比</h1>
          <p className="text-sm text-zinc-500 mt-0.5">论文 4.2 节核心对比表 · 57 个真实实验</p>
        </div>
      </header>

      {/* 4 方法对比 */}
      <div className="rounded-lg border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-zinc-900 mb-4">四方法 Acc@1 对比</h3>
        <div className="space-y-4">
          {data.methods.map((m) => {
            const isOurs = m.name.includes("本文");
            return (
              <div key={m.name}>
                <div className="flex items-center justify-between mb-2">
                  <span className={cn(
                    "text-sm font-medium",
                    isOurs ? "text-emerald-700" : "text-zinc-700"
                  )}>
                    {m.name}
                    {isOurs && <span className="ml-2 text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded">本文方法</span>}
                  </span>
                  <span className={cn(
                    "text-sm font-mono font-bold",
                    isOurs ? "text-emerald-700" : "text-zinc-900"
                  )}>
                    {m.overall.toFixed(1)}%
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-xs">
                  {[
                    { label: "CPU", val: m.cpu, color: "bg-amber-200" },
                    { label: "NETWORK", val: m.network, color: "bg-blue-200" },
                    { label: "POD_KILL", val: m.pod_kill, color: "bg-emerald-200" },
                    { label: `推理 ${m.avg_time}s`, val: 0, color: "" },
                  ].map((cell, i) => (
                    <div key={i} className="bg-zinc-50 rounded p-2">
                      <div className="text-[9px] text-zinc-500 mb-1">{cell.label}</div>
                      {cell.val > 0 ? (
                        <>
                          <div className="font-mono font-medium text-zinc-900">{cell.val.toFixed(1)}%</div>
                          <div className={cn("mt-1 h-1 rounded", cell.color)} style={{ width: `${(cell.val / maxVal) * 100}%` }} />
                        </>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 按故障类型 */}
      <div className="rounded-lg border border-zinc-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-zinc-900 mb-4">按故障类型性能（本文方法）</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-200 text-xs text-zinc-500 uppercase tracking-wider">
              <th className="text-left py-2 font-medium">故障类型</th>
              <th className="text-right py-2 font-medium">实验数</th>
              <th className="text-right py-2 font-medium">系统1 检测</th>
              <th className="text-right py-2 font-medium">ACR</th>
              <th className="text-right py-2 font-medium">MTTD</th>
              <th className="text-right py-2 font-medium">系统2 Acc</th>
              <th className="text-right py-2 font-medium">SOP MTTR</th>
            </tr>
          </thead>
          <tbody>
            {data.fault_types.map((f) => (
              <tr key={f.type} className="border-b border-zinc-100 last:border-0">
                <td className="py-3 font-medium text-zinc-900">{f.type}</td>
                <td className="text-right font-mono">{f.n}</td>
                <td className="text-right font-mono">{f.sys1_detect.toFixed(1)}%</td>
                <td className="text-right font-mono">{f.acr.toFixed(1)}%</td>
                <td className="text-right font-mono">{f.mttd}s</td>
                <td className="text-right font-mono font-semibold text-emerald-700">{f.sys2_acc.toFixed(1)}%</td>
                <td className="text-right font-mono">{f.mttr ? `${f.mttr}s` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
