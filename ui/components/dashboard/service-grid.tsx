"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { api, type ServiceNode } from "@/lib/api";

const STATUS_STYLES = {
  running: "bg-emerald-50 border-emerald-200 text-emerald-700",
  warning: "bg-amber-50 border-amber-300 text-amber-800",
  error: "bg-red-50 border-red-300 text-red-800",
  anomaly: "bg-red-50 border-red-300 text-red-800",
};

const STATUS_DOT = {
  running: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-red-500",
  anomaly: "bg-red-500",
};

export default function ServiceGrid() {
  const [services, setServices] = useState<ServiceNode[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.services()
      .then(d => setServices(d.services))
      .catch(console.error)
      .finally(() => setLoading(false));
    
    const timer = setInterval(() => {
      api.services()
        .then(d => setServices(d.services))
        .catch(console.error);
    }, 10000);
    return () => clearInterval(timer);
  }, []);

  if (loading) return <div className="text-sm text-zinc-500">加载服务网格...</div>;

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">微服务网格</h3>
          <p className="text-xs text-zinc-500 mt-0.5">共 {services.length} 个 Pod · 实时状态</p>
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono">
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />Running</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-500" />Warning</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-500" />Error</span>
        </div>
      </div>

      <div className="grid grid-cols-6 gap-2">
        {services.map((svc) => (
          <div
            key={svc.pod}
            className={cn(
              "border rounded p-2 text-xs transition-all cursor-default hover:shadow-sm",
              STATUS_STYLES[svc.status]
            )}
            title={`Pod: ${svc.pod}\nHost: ${svc.host}\nCPU: ${svc.cpu}%\nMem: ${svc.memory_mb} MB\n重启: ${svc.restart_count} 次`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className={cn("w-1.5 h-1.5 rounded-full", STATUS_DOT[svc.status])} />
              <span className="font-mono text-[9px] opacity-70">{svc.cpu.toFixed(1)}%</span>
            </div>
            <div className="font-mono text-[10px] truncate font-medium">
              {svc.name.replace("ts-", "").replace("-service", "")}
            </div>
            {svc.restart_count > 0 && (
              <div className="text-[9px] mt-0.5 opacity-70">↻ {svc.restart_count}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
