"use client";

import { useEffect, useMemo, useState } from "react";
import ReactFlow, { Background, Controls, MarkerType, Position, type Node, type Edge } from "reactflow";
import "reactflow/dist/style.css";
import { Network, Loader2 } from "lucide-react";
import { api, type GraphNode, type GraphEdge } from "@/lib/api";

const NODE_STYLES = {
  Host: { background: "#eff6ff", border: "2px solid #60a5fa", color: "#1e3a8a", width: 160 },
  Pod: { background: "#fff7ed", border: "2px solid #fb923c", color: "#7c2d12", width: 200 },
  Service: { background: "#ecfdf5", border: "2px solid #34d399", color: "#064e3b", width: 180 },
} as const;

export default function GraphPage() {
  const [data, setData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.topology()
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const { flowNodes, flowEdges } = useMemo(() => {
    if (!data) return { flowNodes: [], flowEdges: [] };
    
    // 力导向式布局：按类型分层
    const typeOrder = { Host: 0, Service: 1, Pod: 2 };
    const buckets: Record<string, GraphNode[]> = { Host: [], Service: [], Pod: [] };
    data.nodes.forEach(n => { buckets[n.type]?.push(n); });
    
    const positions: Record<string, { x: number; y: number }> = {};
    const ROW_Y = { Host: 50, Service: 250, Pod: 480 };
    Object.entries(buckets).forEach(([type, list]) => {
      const startX = type === "Host" ? 600 : 50;
      list.forEach((n, i) => {
        positions[n.id] = {
          x: startX + i * (type === "Host" ? 200 : type === "Service" ? 230 : 230),
          y: ROW_Y[type as keyof typeof ROW_Y],
        };
      });
    });

    const nodes: Node[] = data.nodes.map((n) => ({
      id: n.id,
      position: positions[n.id] || { x: 0, y: 0 },
      data: {
        label: (
          <div className="text-xs leading-tight">
            <div className="text-[9px] uppercase tracking-wider opacity-60 mb-0.5 font-semibold">{n.type}</div>
            <div className="font-mono font-semibold truncate">{n.label}</div>
          </div>
        ),
      },
      style: {
        ...NODE_STYLES[n.type],
        ...(n.status === "error" ? { background: "#fef2f2", borderColor: "#ef4444" } : {}),
        fontSize: 11,
        padding: 8,
        borderRadius: 6,
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    }));

    const edgeColors: Record<string, string> = {
      CALLS: "#10b981",
      BACKEND_OF: "#f59e0b",
      DEPLOY_ON: "#3b82f6",
    };
    const edges: Edge[] = data.edges.map((e, i) => ({
      id: `e${i}`,
      source: e.source,
      target: e.target,
      label: e.type,
      labelStyle: { fill: edgeColors[e.type] || "#666", fontSize: 9, fontFamily: "monospace" },
      labelBgStyle: { fill: "#fff" },
      style: { stroke: edgeColors[e.type] || "#999", strokeWidth: 1.5 },
      markerEnd: { type: MarkerType.ArrowClosed, color: edgeColors[e.type] || "#999" },
      animated: e.type === "CALLS",
    }));

    return { flowNodes: nodes, flowEdges: edges };
  }, [data]);

  return (
    <div className="p-6 space-y-4 max-w-[1600px]">
      <header className="flex items-center gap-2">
        <Network className="w-5 h-5 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">知识图谱</h1>
          <p className="text-sm text-zinc-500 mt-0.5">
            Neo4j 真实拓扑 · {data ? `${data.nodes.length} 节点 / ${data.edges.length} 边` : "..."}
          </p>
        </div>
      </header>

      <div className="h-[700px] rounded-lg border border-zinc-200 bg-zinc-50/30 overflow-hidden">
        {loading ? (
          <div className="h-full flex items-center justify-center text-zinc-500">
            <Loader2 className="w-6 h-6 animate-spin mr-2" /> 加载图谱...
          </div>
        ) : (
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#d4d4d8" gap={20} />
            <Controls />
          </ReactFlow>
        )}
      </div>
    </div>
  );
}
