/**
 * AIOps UI - API Client
 * 连接 FastAPI 后端 (port 9001)
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:9001";

// ============ TypeScript 类型定义 ============
export type ServiceStatus = "running" | "anomaly" | "warning" | "error";

export interface ClusterSummary {
  cluster: {
    total_pods: number;
    running_pods: number;
    ready_pods: number;
    name: string;
  };
  system1: {
    detection_rate: number;
    mttd_sec: number;
    acr: number;
    model: string;
  };
  system2: {
    acc_at_1: number;
    avg_reasoning_sec: number;
    model: string;
  };
}

export interface ServiceNode {
  name: string;
  pod: string;
  host: string;
  status: ServiceStatus;
  cpu: number;
  memory_mb: number;
  restart_count: number;
  phase: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: "Host" | "Pod" | "Service";
  status?: ServiceStatus;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface BaselineMethod {
  name: string;
  overall: number;
  cpu: number;
  network: number;
  pod_kill: number;
  avg_time: number;
}

export interface FaultTypeStat {
  type: string;
  n: number;
  sys1_detect: number;
  acr: number;
  mttd: number;
  sys2_acc: number;
  mttr: number | null;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface DiagnoseStep {
  step: number;
  phase: "system1" | "system2" | "execution";
  type: "thought" | "tool_call" | "result";
  title: string;
  content: string;
}

export interface DiagnoseResult {
  exp_id: string;
  target_service: string;
  root_cause: string;
  confidence: number;
  elapsed_sec: number;
  n_tools: number;
  steps: DiagnoseStep[];
}

// ============ API 调用 ============
async function fetchAPI<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json();
}

export const api = {
  clusterSummary: () => fetchAPI<ClusterSummary>("/api/cluster/summary"),
  
  services: () => fetchAPI<{ services: ServiceNode[]; total: number }>("/api/services"),
  
  topology: () => fetchAPI<{ nodes: GraphNode[]; edges: GraphEdge[] }>("/api/topology"),
  
  experiments: () => fetchAPI<{ experiments: Record<string, unknown>[] }>("/api/experiments"),
  
  baselines: () =>
    fetchAPI<{ methods: BaselineMethod[]; fault_types: FaultTypeStat[] }>("/api/baselines"),
  
  chat: (message: string, history: ChatMessage[] = []) =>
    fetchAPI<{ reply: string; usage?: Record<string, number> }>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, history }),
    }),
  
  diagnose: (exp_id?: string, target_service?: string) =>
    fetchAPI<DiagnoseResult>("/api/diagnose", {
      method: "POST",
      body: JSON.stringify({ exp_id, target_service }),
    }),
};
