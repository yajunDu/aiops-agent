"""
核心数据契约（项目的脊柱）
================================
这些 dataclass 把"感知→认知→执行→记忆"四层的接口固定下来。
最关键的两个设计决策，直接对应冲奖的两个支柱：

  • AnomalySlice.suspect_services 明确标注为"候选，不是答案"
    —— 强制 Agent 去【定位】根因服务，而不是给已圈定对象贴标签。
  • Diagnosis.root_cause_service + propagation_path
    —— 输出从"故障三分类"升级为"服务级根因定位 + 可解释传播链"。

Evidence 把"工具原始观测"与"LLM 的解读"分开存放，是支柱③（去规则化、
让判断来自模型推理而非硬编码阈值）能被审计、能写进论文的前提。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class FaultType(str, Enum):
    CPU = "CPU"            # 计算资源耗尽
    NETWORK = "NETWORK"    # 网络通信劣化
    POD_KILL = "POD_KILL"  # 拓扑硬中断
    DB_SLOW = "DB_SLOW"    # 下游依赖 / 慢查询（旧项目砍掉的，本轮纳入扩展）
    MEM_LEAK = "MEM_LEAK"  # 内存泄漏
    CASCADE = "CASCADE"    # 级联 / 多服务故障
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, s: str) -> "FaultType":
        try:
            return cls((s or "").strip().upper())
        except ValueError:
            return cls.UNKNOWN


@dataclass
class Evidence:
    """Agent 通过一次工具调用获得的一条证据。"""
    tool: str
    args: dict
    observation: str            # 工具返回的（截断后）原始观测
    interpretation: str = ""    # LLM 从中读出的结论（可选，便于审计）
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnomalySlice:
    """系统1（感知）输出，系统2（认知）输入。

    suspect_* 是孤立森林给出的【候选】，不是根因答案。
    """
    slice_id: str
    t_start: int
    t_end: int
    suspect_pods: list[str] = field(default_factory=list)
    suspect_services: list[str] = field(default_factory=list)
    max_score: float = 0.0
    n_windows: int = 0

    @staticmethod
    def service_of_pod(pod: str) -> str:
        """ts-gateway-service-645fbbbdc5-d5q2s → ts-gateway-service

        按 k8s 标准命名 <deployment>-<replicaset哈希>-<pod哈希> 剥离尾部哈希。
        """
        import re
        # Deployment Pod：尾部 -<rs哈希(6-10)>-<pod哈希(5)>
        s = re.sub(r"-[a-z0-9]{6,10}-[a-z0-9]{5}$", "", pod)
        if s == pod:
            # 退化情况：裸 Pod 仅一段哈希
            s = re.sub(r"-[a-z0-9]{5}$", "", pod)
        return s or pod

    def ensure_services(self) -> "AnomalySlice":
        if not self.suspect_services and self.suspect_pods:
            seen, svcs = set(), []
            for p in self.suspect_pods:
                s = self.service_of_pod(p)
                if s not in seen:
                    seen.add(s)
                    svcs.append(s)
            self.suspect_services = svcs
        return self


@dataclass
class PropagationPath:
    """可解释的故障传播链：根因 → … → 观测到的症状。"""
    hops: list[str]                       # 有序服务名，根因在前
    edges: list[tuple[str, str]] = field(default_factory=list)  # (caller, callee)
    rationale: str = ""                   # 为什么是这个方向（LLM 给出）

    def to_dict(self) -> dict:
        return {"hops": self.hops, "edges": [list(e) for e in self.edges], "rationale": self.rationale}


@dataclass
class Diagnosis:
    """系统2 输出 —— 真正的交付物：根因定位 + 类型 + 可解释传播链。"""
    slice_id: str
    root_cause_service: str
    fault_type: FaultType
    confidence: float
    propagation_path: Optional[PropagationPath] = None
    affected_services: list[str] = field(default_factory=list)
    evidence_chain: list[Evidence] = field(default_factory=list)
    summary: str = ""
    n_tool_calls: int = 0
    latency_sec: float = 0.0
    matched_case_id: Optional[str] = None  # 命中的历史案例（支柱②）
    model_name: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fault_type"] = self.fault_type.value
        if self.propagation_path:
            d["propagation_path"] = self.propagation_path.to_dict()
        return d


@dataclass
class IncidentCase:
    """闭环后写回记忆的一条案例（支柱②自学习的存储单元）。"""
    case_id: str
    slice_signature: dict                 # 用于检索的紧凑特征
    diagnosis: dict                       # Diagnosis.to_dict()
    remediation: Optional[dict] = None    # 采取的 SOP
    recovered: Optional[bool] = None
    mttr_sec: Optional[float] = None
    ground_truth: Optional[dict] = None   # 评测时已知
    created_at: float = field(default_factory=time.time)

    @staticmethod
    def new_id() -> str:
        return f"case-{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> dict:
        return asdict(self)
