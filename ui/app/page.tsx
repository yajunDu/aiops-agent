"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, Zap, Server, Brain } from "lucide-react";
import StatCard from "@/components/dashboard/stat-card";
import ServiceGrid from "@/components/dashboard/service-grid";
import { api, type ClusterSummary, type ServiceNode } from "@/lib/api";

export default function HomePage() {
  const [summary, setSummary] = useState<ClusterSummary | null>(null);
  const [services, setServices] = useState<ServiceNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  const loadData = async () => {
    try {
      const [sum, svc] = await Promise.all([
        api.clusterSummary(),
        api.services(),
      ]);
      setSummary(sum);
      setServices(svc.services);
      setError(null);
      setLastUpdate(new Date());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 5000); // 5 秒刷新
    return () => clearInterval(timer);
  }, []);

  if (loading) return <div className="p-6 text-zinc-500">加载中...</div>;
  if (error) return <div className="p-6 text-red-500">连接后端失败: {error}<br/>请确认 http://localhost:9001 在运行</div>;
  if (!summary) return null;

  const errorCount = services.filter(n => n.status === "error").length;
  const warningCount = services.filter(n => n.status === "warning").length;

  return (
    <div className="p-6 space-y-6 max-w-[1600px]">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">总览大盘</h1>
          <p className="text-sm text-zinc-500 mt-1">
            集群健康状态、异常实时监控、双过程系统协同运行视图
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <div className="w-2 h-2 rounded-full bg-emerald-500 status-glow"></div>
          <span className="text-zinc-500 font-mono">
            {lastUpdate.toLocaleTimeString()} · 5s 刷新
          </span>
        </div>
      </header>

      {/* 4 KPI 卡片 */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard
          label="活跃微服务"
          value={summary.cluster.ready_pods}
          unit={`/${summary.cluster.total_pods}`}
          trend={`${((summary.cluster.ready_pods / summary.cluster.total_pods) * 100).toFixed(0)}% 就绪`}
          trendDirection="stable"
          icon={Server}
          variant="success"
        />
        <StatCard
          label="异常告警"
          value={errorCount + warningCount}
          unit="条"
          trend={`${errorCount} error / ${warningCount} warn`}
          trendDirection="up"
          icon={AlertTriangle}
          variant="warning"
        />
        <StatCard
          label="系统1 检测率"
          value={(summary.system1.detection_rate * 100).toFixed(1)}
          unit="%"
          trend={`ACR ${(summary.system1.acr * 100).toFixed(0)}%`}
          trendDirection="stable"
          icon={Zap}
          variant="success"
        />
        <StatCard
          label="系统2 Acc@1"
          value={(summary.system2.acc_at_1 * 100).toFixed(1)}
          unit="%"
          trend={`推理 ${summary.system2.avg_reasoning_sec}s`}
          trendDirection="down"
          icon={Brain}
          variant="default"
        />
      </div>

      {/* 服务网格 */}
      <ServiceGrid />

      {/* 双系统状态 */}
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-zinc-200 bg-white p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-600" />
              <h3 className="text-sm font-semibold text-zinc-900">系统 1（快系统）</h3>
              <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded font-mono">活跃</span>
            </div>
          </div>
          <p className="text-xs text-zinc-500 mb-3">{summary.system1.model} · 边缘侧实时运行</p>
          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between"><span className="text-zinc-500">检测率</span><span className="text-zinc-900 font-medium">{(summary.system1.detection_rate * 100).toFixed(1)}%</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">平均 MTTD</span><span className="text-zinc-900 font-medium">{summary.system1.mttd_sec}s</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">告警压缩率</span><span className="text-emerald-600 font-medium">{(summary.system1.acr * 100).toFixed(0)}%</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">部署</span><span className="text-zinc-900 font-medium">{summary.cluster.name}</span></div>
          </div>
        </div>

        <div className="rounded-lg border border-zinc-200 bg-white p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Brain className="w-4 h-4 text-emerald-600" />
              <h3 className="text-sm font-semibold text-zinc-900">系统 2（慢系统）</h3>
              <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-mono">推理中</span>
            </div>
          </div>
          <p className="text-xs text-zinc-500 mb-3">{summary.system2.model} · GraphRAG + Tool-Calling</p>
          <div className="space-y-2 text-xs font-mono">
            <div className="flex justify-between"><span className="text-zinc-500">Acc@1</span><span className="text-zinc-900 font-medium">{(summary.system2.acc_at_1 * 100).toFixed(1)}%</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">平均推理</span><span className="text-zinc-900 font-medium">{summary.system2.avg_reasoning_sec}s</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">工具调用</span><span className="text-emerald-600 font-medium">Cypher + Prom</span></div>
            <div className="flex justify-between"><span className="text-zinc-500">输出</span><span className="text-zinc-900 font-medium">JSON 严格</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}
