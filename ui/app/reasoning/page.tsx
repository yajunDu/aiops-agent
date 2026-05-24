"use client";

import { useEffect, useRef, useState } from "react";
import { Brain, Send, Bot, User, Loader2, Sparkles } from "lucide-react";
import { api, type ChatMessage, type DiagnoseResult } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ReasoningPage() {
  // ============ 自由问答 ============
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || sending) return;
    const userMsg: ChatMessage = { role: "user", content: input };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setSending(true);

    try {
      const res = await api.chat(input, messages);
      setMessages([...newMessages, { role: "assistant", content: res.reply }]);
    } catch (e) {
      setMessages([...newMessages, { role: "assistant", content: `❌ 调用失败: ${(e as Error).message}` }]);
    } finally {
      setSending(false);
    }
  };

  // ============ Agent 推理 ============
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnose, setDiagnose] = useState<DiagnoseResult | null>(null);

  const runDiagnose = async () => {
    setDiagnosing(true);
    try {
      const res = await api.diagnose();
      setDiagnose(res);
    } catch (e) {
      alert(`推理失败: ${(e as Error).message}`);
    } finally {
      setDiagnosing(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-[1600px]">
      <header>
        <h1 className="text-2xl font-bold text-zinc-900">双系统推理</h1>
        <p className="text-sm text-zinc-500 mt-1">
          系统 1 异常切片 · 系统 2 LLM Agent 工具调用 · 实时根因诊断
        </p>
      </header>

      <div className="grid grid-cols-2 gap-6">
        {/* ============ 左侧：自由问答 ============ */}
        <div className="rounded-lg border border-zinc-200 bg-white flex flex-col h-[650px]">
          <div className="px-5 py-3 border-b border-zinc-200 flex items-center gap-2">
            <Bot className="w-4 h-4 text-blue-600" />
            <h3 className="text-sm font-semibold text-zinc-900">自由问诊</h3>
            <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-mono">Qwen2.5-7B</span>
          </div>

          <div className="flex-1 overflow-y-auto p-5 space-y-3">
            {messages.length === 0 && (
              <div className="text-center text-sm text-zinc-400 mt-20">
                <Sparkles className="w-8 h-8 mx-auto mb-3 text-zinc-300" />
                向 AI 提问，例如：<br/>
                <span className="text-xs font-mono mt-2 inline-block">
                  · 什么是 Pod CrashLoopBackOff？<br/>
                  · 解释一下孤立森林算法的原理<br/>
                  · 我的集群有 24 个服务持续重启，怎么排查？
                </span>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={cn(
                "flex gap-2",
                m.role === "user" ? "justify-end" : "justify-start"
              )}>
                {m.role === "assistant" && (
                  <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                    <Bot className="w-4 h-4 text-blue-600" />
                  </div>
                )}
                <div className={cn(
                  "max-w-[80%] rounded-lg px-3 py-2 text-sm",
                  m.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-zinc-100 text-zinc-900"
                )}>
                  <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
                </div>
                {m.role === "user" && (
                  <div className="w-7 h-7 rounded-full bg-zinc-200 flex items-center justify-center flex-shrink-0">
                    <User className="w-4 h-4 text-zinc-600" />
                  </div>
                )}
              </div>
            ))}
            {sending && (
              <div className="flex gap-2">
                <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center">
                  <Bot className="w-4 h-4 text-blue-600" />
                </div>
                <div className="bg-zinc-100 rounded-lg px-3 py-2 text-sm text-zinc-500 flex items-center gap-2">
                  <Loader2 className="w-3 h-3 animate-spin" /> 思考中...
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <div className="px-5 py-3 border-t border-zinc-200 flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendMessage()}
              disabled={sending}
              placeholder="输入问题..."
              className="flex-1 text-sm px-3 py-2 border border-zinc-200 rounded-md focus:outline-none focus:border-blue-400"
            />
            <button
              onClick={sendMessage}
              disabled={sending || !input.trim()}
              className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm flex items-center gap-1.5 disabled:opacity-50 hover:bg-blue-700"
            >
              <Send className="w-3.5 h-3.5" /> 发送
            </button>
          </div>
        </div>

        {/* ============ 右侧：Agent 真推理 ============ */}
        <div className="rounded-lg border border-zinc-200 bg-white flex flex-col h-[650px]">
          <div className="px-5 py-3 border-b border-zinc-200 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Brain className="w-4 h-4 text-emerald-600" />
              <h3 className="text-sm font-semibold text-zinc-900">根因诊断（LangGraph Agent）</h3>
              <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded font-mono">Tool-Calling</span>
            </div>
            <button
              onClick={runDiagnose}
              disabled={diagnosing}
              className="px-3 py-1.5 bg-emerald-600 text-white rounded-md text-xs flex items-center gap-1.5 disabled:opacity-50 hover:bg-emerald-700"
            >
              {diagnosing ? <><Loader2 className="w-3 h-3 animate-spin" /> 推理中</> : <>▶ 执行诊断</>}
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {!diagnose && !diagnosing && (
              <div className="text-center text-sm text-zinc-400 mt-20">
                <Brain className="w-8 h-8 mx-auto mb-3 text-zinc-300" />
                点击 &quot;执行诊断&quot; 触发 Agent 真推理<br/>
                <span className="text-xs font-mono mt-2 inline-block">
                  默认场景：ts-gateway-service CPU 故障注入<br/>
                  约耗时 5 秒（含 3 轮工具调用）
                </span>
              </div>
            )}

            {diagnosing && (
              <div className="text-center text-sm text-zinc-500 mt-20">
                <Loader2 className="w-8 h-8 mx-auto mb-3 animate-spin text-emerald-500" />
                Agent 正在调用工具...<br/>
                <span className="text-xs font-mono text-zinc-400">query_graph_topology → get_pod_metrics</span>
              </div>
            )}

            {diagnose && (
              <div className="space-y-3">
                {/* 结论卡 */}
                <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3">
                  <div className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold mb-1">最终结论</div>
                  <p className="text-sm font-medium text-emerald-900">{diagnose.root_cause}</p>
                  <div className="flex gap-4 mt-2 text-xs text-emerald-700 font-mono">
                    <span>置信度 {(diagnose.confidence * 100).toFixed(0)}%</span>
                    <span>{diagnose.elapsed_sec}s</span>
                    <span>{diagnose.n_tools} 次工具调用</span>
                  </div>
                </div>

                {/* 步骤列表 */}
                {diagnose.steps.map((s) => (
                  <div key={s.step} className="border-l-2 border-zinc-200 pl-3 py-1">
                    <div className="flex items-center gap-2 text-xs text-zinc-500">
                      <span className="font-mono text-blue-600">#{s.step}</span>
                      <span className="font-mono uppercase tracking-wide text-[10px]">{s.type}</span>
                      <span className="font-medium text-zinc-700">{s.title}</span>
                    </div>
                    <pre className="text-xs font-mono text-zinc-600 whitespace-pre-wrap mt-1 bg-zinc-50 rounded p-2 max-h-32 overflow-y-auto">
                      {s.content}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
