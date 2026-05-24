// TrainTicket 41 个微服务（与论文 4.1.1 节一致）
export const SERVICES = [
  "ts-admin-basic-info-service", "ts-admin-order-service", "ts-admin-route-service",
  "ts-admin-travel-service", "ts-admin-user-service", "ts-assurance-service",
  "ts-auth-service", "ts-avatar-service", "ts-basic-service", "ts-cancel-service",
  "ts-config-service", "ts-consign-price-service", "ts-consign-service",
  "ts-contacts-service", "ts-delivery-service", "ts-execute-service",
  "ts-food-delivery-service", "ts-food-service", "ts-gateway-service",
  "ts-inside-payment-service", "ts-news-service", "ts-notification-service",
  "ts-order-other-service", "ts-order-service", "ts-payment-service",
  "ts-preserve-other-service", "ts-preserve-service", "ts-price-service",
  "ts-rebook-service", "ts-route-plan-service", "ts-route-service",
  "ts-seat-service", "ts-security-service", "ts-station-service",
  "ts-train-service", "ts-travel-plan-service", "ts-travel-service",
  "ts-travel2-service", "ts-ui-dashboard", "ts-user-service",
  "ts-verification-code-service",
];

export type ServiceStatus = "running" | "anomaly" | "warning" | "error";

export interface ServiceNode {
  name: string;
  status: ServiceStatus;
  cpu: number;       // 0-100
  memory: number;    // 0-100
  qps: number;       // requests/sec
  p95Latency: number; // ms
  pod: string;
  host: string;
  group: string;
}

const GROUP_MAP: Record<string, string> = {
  admin: "管理服务", auth: "认证授权", order: "订单核心",
  travel: "出行核心", payment: "支付清算", food: "餐饮服务",
  user: "用户体系", train: "列车调度", route: "路线规划",
  station: "车站服务", contacts: "联系人", basic: "基础数据",
  gateway: "网关入口", ui: "前端入口", config: "配置中心",
};

function getGroup(name: string): string {
  for (const [key, label] of Object.entries(GROUP_MAP)) {
    if (name.includes(key)) return label;
  }
  return "其他服务";
}

function hashCode(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = ((hash << 5) - hash) + s.charCodeAt(i);
    hash = hash & hash;
  }
  return Math.abs(hash);
}

// 论文 4.2 节场景：注入了 CPU 耗尽故障到 ts-order-service
// 受害者：ts-gateway / ts-travel / ts-preserve（级联告警风暴）
export const ANOMALY_ROOT = "ts-order-service";
export const ANOMALY_VICTIMS = ["ts-gateway-service", "ts-travel-service", "ts-preserve-service"];

export const SERVICE_NODES: ServiceNode[] = SERVICES.map((name) => {
  const h = hashCode(name);
  const isRoot = name === ANOMALY_ROOT;
  const isVictim = ANOMALY_VICTIMS.includes(name);

  let status: ServiceStatus = "running";
  let cpu = 5 + (h % 30);
  let memory = 20 + (h % 35);
  let p95 = 50 + (h % 80);
  let qps = 10 + (h % 80);

  if (isRoot) {
    status = "error";
    cpu = 94; memory = 78; p95 = 850; qps = 12;
  } else if (isVictim) {
    status = "warning";
    cpu = 65 + (h % 15); memory = 55; p95 = 320 + (h % 100);
  }

  const podHash = (h % 90000) + 10000;
  return {
    name, status, cpu, memory, qps, p95Latency: p95,
    pod: `${name}-${podHash}-${name.slice(-5)}`,
    host: h % 3 === 0 ? "fresne" : `worker-${h % 3}`,
    group: getGroup(name),
  };
});

// 时序数据（最近 30 分钟，每 30 秒一个点）
export interface TimePoint {
  time: string;
  value: number;
  isAnomaly?: boolean;
}

export function generateTimeSeries(baseline: number, anomalyAt?: number): TimePoint[] {
  const points: TimePoint[] = [];
  const now = new Date();
  for (let i = 60; i >= 0; i--) {
    const t = new Date(now.getTime() - i * 30000);
    const ms = t.getMinutes().toString().padStart(2, '0');
    const ss = t.getSeconds().toString().padStart(2, '0');
    const time = `${t.getHours()}:${ms}:${ss}`;
    const noise = (Math.sin(i * 0.7) + Math.cos(i * 0.3)) * 5;
    let value = baseline + noise;
    let isAnomaly = false;
    if (anomalyAt !== undefined && i <= anomalyAt && i >= anomalyAt - 8) {
      value = baseline + 60 + Math.sin(i * 0.5) * 10;
      isAnomaly = true;
    }
    points.push({ time, value: Math.max(0, Math.round(value * 10) / 10), isAnomaly });
  }
  return points;
}

// 论文 4.2 表 4.1 数据
export const EXPERIMENT_RESULTS = {
  acc: [
    { method: "Rule-Based", "Acc@1": 15, "Acc@3": 28, "Acc@5": 35 },
    { method: "MicroRCA", "Acc@1": 42, "Acc@3": 68, "Acc@5": 75 },
    { method: "Naive LLM+RAG", "Acc@1": 35, "Acc@3": 52, "Acc@5": 61 },
    { method: "本文 (双过程)", "Acc@1": 92, "Acc@3": 96, "Acc@5": 98 },
  ],
  mttd: [
    { method: "Rule-Based", min: 200, q1: 240, median: 280, q3: 340, max: 420 },
    { method: "MicroRCA", min: 130, q1: 160, median: 180, q3: 215, max: 260 },
    { method: "Naive LLM+RAG", min: 180, q1: 215, median: 240, q3: 280, max: 380 },
    { method: "本文 (双过程)", min: 80, q1: 92, median: 102, q3: 118, max: 140 },
  ],
  scenarios: [
    { type: "计算资源耗尽", acr: 98.5, mttd: 102, mttr: 120 },
    { type: "网络通信劣化", acr: 97.2, mttd: 95, mttr: 110 },
    { type: "拓扑物理强杀", acr: 99.1, mttd: 85, mttr: 90 },
    { type: "下游状态死锁", acr: 97.9, mttd: 96, mttr: 105 },
  ],
};

// Tool-Calling 推理步骤（论文 3.3 + 4.2.3 节）
export interface ReasoningStep {
  step: number;
  phase: "system1" | "system2" | "execution";
  type: "anomaly_slice" | "tool_call" | "thought" | "cypher" | "result" | "sop";
  title: string;
  content: string;
  duration_ms?: number;
  metadata?: Record<string, string | number>;
}

export const REASONING_TIMELINE: ReasoningStep[] = [
  {
    step: 1, phase: "system1", type: "anomaly_slice",
    title: "系统 1：孤立森林告警切片",
    content: "原始告警 1247 条 → 收敛为 12 条异常切片\n压缩率: 98.5%\n锚定服务: ts-order-service, ts-gateway-service, ts-travel-service",
    duration_ms: 1800,
    metadata: { raw_alerts: 1247, anomalies: 12, compression_rate: "98.5%" },
  },
  {
    step: 2, phase: "system2", type: "thought",
    title: "系统 2：因果推理初始假设",
    content: "观察到告警风暴集中在订单链路。基于业务先验：ts-gateway → ts-order → ts-train 是核心调用路径。三者同时告警，但 ts-gateway 是入口，受害概率最高。需要查询拓扑确认根因方向。",
    duration_ms: 4200,
  },
  {
    step: 3, phase: "system2", type: "tool_call",
    title: "Tool Call #1: query_graph_topology",
    content: "查询订单链路上下游服务关系",
    duration_ms: 320,
    metadata: { tool: "query_graph_topology", target: "ts-order-service" },
  },
  {
    step: 4, phase: "system2", type: "cypher",
    title: "Cypher 物理试探",
    content: `MATCH (s:Service {name: 'ts-order-service'})
OPTIONAL MATCH (s)-[:CALLS]->(downstream:Service)
OPTIONAL MATCH (upstream:Service)-[:CALLS]->(s)
RETURN s.name AS root,
       collect(DISTINCT downstream.name) AS downstream_services,
       collect(DISTINCT upstream.name) AS upstream_services`,
    duration_ms: 45,
  },
  {
    step: 5, phase: "system2", type: "result",
    title: "图谱返回事实",
    content: `root: ts-order-service
upstream_services: [ts-gateway-service, ts-ui-dashboard]
downstream_services: [ts-train-service, ts-seat-service, ts-payment-service, ts-user-service]
→ 阻断 LLM 沿"网关问题"幻觉方向的发散`,
    duration_ms: 12,
  },
  {
    step: 6, phase: "system2", type: "tool_call",
    title: "Tool Call #2: get_pod_metrics",
    content: "获取 ts-order-service Pod 的实时资源指标",
    duration_ms: 280,
    metadata: { tool: "get_pod_metrics", target: "ts-order-service" },
  },
  {
    step: 7, phase: "system2", type: "result",
    title: "指标返回",
    content: `pod: ts-order-service-5877dcb978-8n59s
node: fresne (10.161.136.7)
cpu_usage: 94.2%   ← 异常高
memory_usage: 78%
network_io: 12 Mbps (正常)
disk_io: 4 KB/s (正常)
→ CPU 是瓶颈，定位 ts-order-service`,
    duration_ms: 18,
  },
  {
    step: 8, phase: "system2", type: "thought",
    title: "因果链确认",
    content: "证据链闭合：\n① ts-order-service CPU 94% 持续异常\n② 下游服务（train/seat/payment）指标正常\n③ 上游服务（gateway/ui）告警是 503，符合超时级联\n→ 根因: ts-order-service CPU 耗尽\n→ 受害者: ts-gateway, ts-travel, ts-preserve (cascade)",
    duration_ms: 2100,
  },
  {
    step: 9, phase: "execution", type: "sop",
    title: "执行层：原子化 SOP 生成",
    content: `# 安全护栏校验
✓ namespace 已确认: train-ticket
✓ pod 名称已绑定: ts-order-service-5877dcb978-8n59s
✓ 操作权限已确认: 重启权限 (非删除)

# 生成的修复指令
kubectl rollout restart deployment/ts-order-service \\
  -n train-ticket

# 验证窗口: 60s
kubectl wait --for=condition=Ready pod/ts-order-service-* \\
  -n train-ticket --timeout=60s`,
    duration_ms: 850,
  },
];

// 知识图谱节点（用于 Neo4j 可视化）
export interface GraphNode {
  id: string;
  label: string;
  type: "Host" | "Pod" | "Service";
  status?: ServiceStatus;
  metadata?: Record<string, string | number>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: "DEPLOY_ON" | "BACKEND_OF" | "CALLS";
  metadata?: Record<string, string | number>;
}

export const KNOWLEDGE_GRAPH = {
  nodes: [
    { id: "host-fresne", label: "fresne", type: "Host" as const, metadata: { ip: "10.161.136.7", cpu_cores: 8, memory_gb: 24 } },
    { id: "host-worker1", label: "worker-1", type: "Host" as const, metadata: { ip: "10.161.136.8", cpu_cores: 4, memory_gb: 8 } },
    { id: "pod-order", label: "ts-order-service-...", type: "Pod" as const, status: "error" as ServiceStatus, metadata: { cpu: "94%", status: "Running (异常)" } },
    { id: "pod-gateway", label: "ts-gateway-service-...", type: "Pod" as const, status: "warning" as ServiceStatus, metadata: { cpu: "72%", status: "Running" } },
    { id: "pod-train", label: "ts-train-service-...", type: "Pod" as const, status: "running" as ServiceStatus },
    { id: "pod-payment", label: "ts-payment-service-...", type: "Pod" as const, status: "running" as ServiceStatus },
    { id: "pod-seat", label: "ts-seat-service-...", type: "Pod" as const, status: "running" as ServiceStatus },
    { id: "svc-order", label: "ts-order-service", type: "Service" as const, status: "error" as ServiceStatus },
    { id: "svc-gateway", label: "ts-gateway-service", type: "Service" as const, status: "warning" as ServiceStatus },
    { id: "svc-train", label: "ts-train-service", type: "Service" as const, status: "running" as ServiceStatus },
    { id: "svc-payment", label: "ts-payment-service", type: "Service" as const, status: "running" as ServiceStatus },
    { id: "svc-seat", label: "ts-seat-service", type: "Service" as const, status: "running" as ServiceStatus },
  ] as GraphNode[],
  edges: [
    { source: "pod-order", target: "host-fresne", type: "DEPLOY_ON" as const },
    { source: "pod-gateway", target: "host-fresne", type: "DEPLOY_ON" as const },
    { source: "pod-train", target: "host-fresne", type: "DEPLOY_ON" as const },
    { source: "pod-payment", target: "host-worker1", type: "DEPLOY_ON" as const },
    { source: "pod-seat", target: "host-worker1", type: "DEPLOY_ON" as const },
    { source: "pod-order", target: "svc-order", type: "BACKEND_OF" as const },
    { source: "pod-gateway", target: "svc-gateway", type: "BACKEND_OF" as const },
    { source: "pod-train", target: "svc-train", type: "BACKEND_OF" as const },
    { source: "pod-payment", target: "svc-payment", type: "BACKEND_OF" as const },
    { source: "pod-seat", target: "svc-seat", type: "BACKEND_OF" as const },
    { source: "svc-gateway", target: "svc-order", type: "CALLS" as const, metadata: { latency_ms: 320 } },
    { source: "svc-order", target: "svc-train", type: "CALLS" as const, metadata: { latency_ms: 45 } },
    { source: "svc-order", target: "svc-payment", type: "CALLS" as const, metadata: { latency_ms: 38 } },
    { source: "svc-order", target: "svc-seat", type: "CALLS" as const, metadata: { latency_ms: 22 } },
  ] as GraphEdge[],
};
