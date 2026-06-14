# 项目结构（初赛版）

> 范围：一个能稳定跑通"故障注入→检测→根因定位→自愈→恢复确认"闭环、能录演示视频、配齐材料的最小完整系统。**不含记忆环、不含多智能体，全程匿名。**

```
aiops/                                  # 项目根（匿名，不含学校/导师/学号）
├── README.md                           # 匿名版项目说明
├── requirements.txt
├── .env.example                        # 端点配置模板（Neo4j / vLLM / Prometheus）
├── start_all.sh                        # ★一键启动（演示用，关键资产）
│
├── aiops/                              # 核心 Python 包（可 import aiops.*）
│   ├── config.py                       # 集中配置
│   ├── core/
│   │   └── contracts.py                # 数据脊柱 AnomalySlice / Diagnosis / PropagationPath / Evidence
│   │
│   ├── perception/                     # 系统1 · 感知   【复用旧 system1】
│   │   └── detector.py                 # 在线检测 → 输出 AnomalySlice（+CSV回放接口）
│   │
│   ├── cognition/                      # 系统2 · 认知   【新·干净 agent】
│   │   ├── agent.py                    # LangGraph：perceive→investigate→act→synthesize
│   │   ├── prompts.py                  # 去规则化、证据驱动、拓扑因果
│   │   └── tools/
│   │       ├── graph_tools.py          # Neo4j 拓扑 + CALLS 因果方向推理（根因 vs 受害者）
│   │       └── metric_tools.py         # 指标数值证据（实时/回放，不在此套阈值）
│   │
│   ├── remediation/                    # 执行层 · 自愈   【复用旧 sop】
│   │   ├── sop_planner.py              # 选模板 + 4 道护栏（消费 Diagnosis）
│   │   ├── sop_executor.py             # 真 kubectl 执行 + post-check
│   │   └── templates/                  # 5 个 SOP YAML
│   │
│   └── orchestrator.py                 # ★闭环编排 detect→diagnose→remediate→verify【新·demo脊柱】
│
├── graph/
│   └── build_neo4j_graph.py            # 从 K8s 拓扑构建 Neo4j 图谱【复用旧】
│
├── experiments/                        # 混沌注入 + 评测   【复用旧 experiments】
│   ├── chaos_injector.py               # Chaos Mesh 注入（CPU/网络/Pod强杀 3 类）
│   ├── batch_runner.py                 # 批量实验
│   ├── ground-truth/                   # 故障真实标签
│   └── evaluate.py                     # 算 Acc@1 + 端到端指标（出文档的表）
│
├── baselines/                          # 对比基线   【复用旧，初赛建议保留】
│   ├── rule_based.py · microrca.py · naive_llm_rag.py
│
├── ui/  +  ui-backend/                 # 全栈大盘   【复用旧 ui，匿名化；录视频的核心资产】
│
└── docs/                               # 提交材料工作区
    ├── 作品简介.md                      # 300 字
    ├── 项目文档.md                      # 套官方模板
    └── 视频脚本.md                      # 分镜
```

## 闭环数据流（orchestrator 串起来的那条线）

```
detector.detect_anomalies()  →  AnomalySlice（嫌疑服务=候选，非答案）
   → agent.diagnose()        →  Diagnosis（root_cause_service + 传播链 + 类型）
   → sop_planner.remediate() →  选模板 + 4 道护栏 + kubectl 执行
   → orchestrator._verify_recovery() → 业务恢复 + MTTR
   → UI 大盘全程可视化（评委在视频里看到的"系统在动"）
```

## 复用 vs 新写

| 模块 | 来源 |
|---|---|
| perception / remediation / experiments / baselines / graph / ui | **复用**旧项目稳定代码（整理进新结构 + 匿名化） |
| core/contracts · cognition（agent/prompts/tools） | **新**·去规则化 + 拓扑根因定位 |
| orchestrator | **新**·闭环脊柱（旧项目里这条线较薄，最出片） |
| ~~memory · 多智能体~~ | 初赛不做，留给现场答辩 |

## 建议的编码顺序

1. ✅ core/contracts · cognition（去规则化 + 拓扑定位 agent）
2. ✅ orchestrator 脊柱 + perception/remediation 接口
3. ✅ 旧 system1 推理移植进 `perception/detector.py`（+核心服务范围/判别排序两项在线适配）
4. ✅ 旧 sop_planner/executor + 5 模板移植进 `remediation/`（消费 Diagnosis，离线可 dry-run）
5. ✅ 接通 `orchestrator`（回放/在线双驱动 + kubectl 恢复确认）
6. ✅ `graph/build_neo4j_graph.py` + `experiments/evaluate.py` + `run_demo.py`
7. ⬜ UI 接 `orchestrator` 的 on_event 时间线 → 录演示视频（最后一步，录视频用）
```
