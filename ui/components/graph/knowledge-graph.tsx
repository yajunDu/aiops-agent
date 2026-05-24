"use client";

import { useMemo } from "react";
import ReactFlow, {
  Node, Edge, Background, Controls, MarkerType, Position,
} from "reactflow";
import "reactflow/dist/style.css";
import { KNOWLEDGE_GRAPH } from "@/lib/mock-data";

const NODE_STYLES = {
  Host: { background: "#eff6ff", border: "2px solid #60a5fa", color: "#1e3a8a", width: 180 },
  Pod: { background: "#fff7ed", border: "2px solid #fb923c", color: "#7c2d12", width: 200 },
  Service: { background: "#ecfdf5", border: "2px solid #34d399", color: "#064e3b", width: 180 },
};

const STATUS_OVERRIDE = {
  error: { background: "#fef2f2", border: "2px solid #ef4444", boxShadow: "0 0 0 4px rgba(239,68,68,0.15)" },
  warning: { background: "#fffbeb", border: "2px solid #f59e0b", boxShadow: "0 0 0 3px rgba(245,158,11,0.15)" },
};

export default function KnowledgeGraph() {
  const { nodes, edges } = useMemo(() => {
    const positions: Record<string, { x: number; y: number }> = {
      "svc-gateway": { x: 50, y: 50 },
      "svc-order": { x: 280, y: 50 },
      "svc-train": { x: 510, y: 50 },
      "svc-payment": { x: 740, y: 50 },
      "svc-seat": { x: 970, y: 50 },
      "pod-gateway": { x: 50, y: 220 },
      "pod-order": { x: 280, y: 220 },
      "pod-train": { x: 510, y: 220 },
      "pod-payment": { x: 740, y: 220 },
      "pod-seat": { x: 970, y: 220 },
      "host-fresne": { x: 200, y: 400 },
      "host-worker1": { x: 700, y: 400 },
    };

    const flowNodes: Node[] = KNOWLEDGE_GRAPH.nodes.map((n) => {
      const baseStyle = NODE_STYLES[n.type];
      const override = n.status ? STATUS_OVERRIDE[n.status as keyof typeof STATUS_OVERRIDE] : null;
      const metadata = n.metadata
        ? Object.entries(n.metadata).map(([k, v]) => `${k}: ${v}`).join(" · ")
        : "";

      return {
        id: n.id,
        position: positions[n.id] || { x: 0, y: 0 },
        data: {
          label: (
            <div className="text-xs leading-tight">
              <div className="text-[9px] uppercase tracking-wider opacity-60 mb-0.5 font-semibold">{n.type}</div>
              <div className="font-mono font-semibold">{n.label}</div>
              {metadata && <div className="text-[9px] opacity-70 mt-1 font-mono">{metadata}</div>}
            </div>
          ),
        },
        style: {
          ...baseStyle,
          ...(override || {}),
          fontSize: 11,
          padding: 10,
          borderRadius: 8,
          boxShadow: override?.boxShadow || "0 1px 3px rgba(0,0,0,0.05)",
        },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
      };
    });

    const edgeColors = {
      DEPLOY_ON: "#3b82f6",
      BACKEND_OF: "#f59e0b",
      CALLS: "#10b981",
    };

    const flowEdges: Edge[] = KNOWLEDGE_GRAPH.edges.map((e, idx) => ({
      id: `e${idx}`,
      source: e.source,
      target: e.target,
      label: e.metadata?.latency_ms ? `${e.metadata.latency_ms}ms` : e.type,
      labelStyle: { fill: edgeColors[e.type], fontSize: 9, fontFamily: "monospace", fontWeight: 600 },
      labelBgStyle: { fill: "#ffffff", fillOpacity: 1 },
      labelBgPadding: [4, 6],
      labelBgBorderRadius: 4,
      style: {
        stroke: edgeColors[e.type],
        strokeWidth: e.metadata?.latency_ms && Number(e.metadata.latency_ms) > 200 ? 2.5 : 1.5,
        opacity: e.metadata?.latency_ms && Number(e.metadata.latency_ms) > 200 ? 1 : 0.7,
        strokeDasharray: e.type === "BACKEND_OF" ? "4 4" : undefined,
      },
      markerEnd: { type: MarkerType.ArrowClosed, color: edgeColors[e.type] },
      animated: e.type === "CALLS",
    }));

    return { nodes: flowNodes, edges: flowEdges };
  }, []);

  return (
    <div className="h-[560px] rounded-lg border border-zinc-200 bg-zinc-50/30 overflow-hidden">
      <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.15 }} proOptions={{ hideAttribution: true }}>
        <Background color="#d4d4d8" gap={20} />
        <Controls style={{ background: "#ffffff", border: "1px solid #e4e4e7", borderRadius: 6, boxShadow: "0 1px 3px rgba(0,0,0,0.05)" }} />
      </ReactFlow>
    </div>
  );
}
