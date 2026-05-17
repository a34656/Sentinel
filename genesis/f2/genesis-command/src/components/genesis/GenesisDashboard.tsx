import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  Brain,
  CheckCircle2,
  CircleDot,
  Cog,
  Power,
  Search,
  Shield,
  XCircle,
} from "lucide-react";

type AgentKey = "master" | "engineer" | "scout" | "policy";
type StepStatus = "ok" | "fail" | "pending";

interface FeedStep {
  id: number;
  agent: AgentKey;
  ts: string;
  msg: string;
  status: StepStatus;
}

interface Belief {
  key: string;
  label: string;
  prob: number;
}

interface Finding {
  key: string;
  label: string;
  state: "idle" | "violation" | "clean";
  count: number;
}

const AGENT_META: Record<AgentKey, { label: string; icon: typeof Brain; color: string }> = {
  master: { label: "MASTER", icon: Brain, color: "text-genesis-purple" },
  engineer: { label: "ENGINEER", icon: Cog, color: "text-genesis-cyan" },
  scout: { label: "SCOUT", icon: Search, color: "text-genesis-amber" },
  policy: { label: "POLICYGUARD", icon: Shield, color: "text-genesis-green" },
};

const FEED_SCRIPT: Omit<FeedStep, "id" | "ts">[] = [
  { agent: "master", msg: "Incident GEN-2148 received · spawning sub-agents", status: "ok" },
  { agent: "scout", msg: "Querying Dynatrace timeseries for cluster prod-eu-1", status: "ok" },
  { agent: "engineer", msg: "Pulling MongoDB billing aggregate (last 24h)", status: "pending" },
  { agent: "policy", msg: "Scanning IAM drift against baseline policy v3.2", status: "ok" },
  { agent: "engineer", msg: "Detected 412% anomaly on egress charges", status: "ok" },
  { agent: "scout", msg: "Correlating with deploy-7c9f3 at 14:02:17Z", status: "ok" },
  { agent: "policy", msg: "S3 bucket genesis-logs flagged: public-read ACL", status: "fail" },
  { agent: "master", msg: "Updating belief vector · entropy ↓", status: "ok" },
  { agent: "engineer", msg: "Provisioning sandbox container for live test", status: "pending" },
  { agent: "scout", msg: "VPC flow logs show 3.2GB/s exfil pattern", status: "fail" },
  { agent: "policy", msg: "KMS key rotation overdue by 47 days", status: "fail" },
  { agent: "master", msg: "Hypothesis converged · confidence threshold reached", status: "ok" },
];


const INITIAL_BELIEFS: Belief[] = [
  { key: "billing", label: "Billing Spike", prob: 14 },
  { key: "resource", label: "Resource Exhaustion", prob: 12 },
  { key: "misconfig", label: "Misconfiguration", prob: 18 },
  { key: "dependency", label: "Dependency Failure", prob: 10 },
  { key: "network", label: "Network Issue", prob: 16 },
  { key: "security", label: "Security Event", prob: 15 },
  { key: "deploy", label: "Deployment Bug", prob: 15 },
];

const TARGET_BELIEFS: Record<string, number> = {
  billing: 8,
  resource: 4,
  misconfig: 11,
  dependency: 3,
  network: 6,
  security: 62,
  deploy: 6,
};

const INITIAL_FINDINGS: Finding[] = [
  { key: "iam", label: "IAM & Access Control", state: "idle", count: 0 },
  { key: "data", label: "Data Protection", state: "idle", count: 0 },
  { key: "network", label: "Network Egress", state: "idle", count: 0 },
  { key: "logging", label: "Logging & Audit", state: "idle", count: 0 },
  { key: "encryption", label: "Encryption at Rest", state: "idle", count: 0 },
];

function formatElapsed(ms: number) {
  const s = Math.floor(ms / 1000);
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${h}:${m}:${ss}`;
}

function nowStamp() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}.${String(d.getMilliseconds()).padStart(3, "0").slice(0, 3)}`;
}

function PanelFrame({
  title,
  meta,
  children,
  className = "",
}: {
  title: string;
  meta?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`relative flex flex-col rounded-sm border border-genesis-border bg-genesis-surface/80 shadow-[0_0_24px_rgba(0,212,255,0.04)_inset] ${className}`}
    >
      <header className="flex items-center justify-between border-b border-genesis-border px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-genesis-cyan shadow-[0_0_6px_var(--color-genesis-cyan)]" />
          <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-genesis-text">
            {title}
          </h2>
        </div>
        {meta && <div className="font-mono text-[10px] uppercase tracking-widest text-genesis-muted">{meta}</div>}
      </header>
      <div className="genesis-scanline flex-1 overflow-hidden">{children}</div>
    </section>
  );
}

export default function GenesisDashboard() {
  const [feed, setFeed] = useState<FeedStep[]>([]);
  const [beliefs, setBeliefs] = useState<Belief[]>(INITIAL_BELIEFS);
  const [findings, setFindings] = useState<Finding[]>(INITIAL_FINDINGS);
  const [approved, setApproved] = useState(false);
  const [aborted, setAborted] = useState(false);
  const [confidence, setConfidence] = useState(31);
  const [entropyStart] = useState(2.4);
  const [entropy, setEntropy] = useState(2.4);
  const [elapsed, setElapsed] = useState(0);
  const [running, setRunning] = useState(true);
  const [activeLine, setActiveLine] = useState<number | null>(null);
  const [completedLines, setCompletedLines] = useState<Set<number>>(new Set());
  const [prompt, setPrompt] = useState("");
  const [submittedPrompt, setSubmittedPrompt] = useState("");
  const [dynamicPlan, setDynamicPlan] = useState<string[]>([]);
  const [dynamicScript, setDynamicScript] = useState<string>("");
  const [loadingPlan, setLoadingPlan] = useState(false);
  const startedAt = useRef(Date.now());
  const feedRef = useRef<HTMLDivElement>(null);
  const activeLineRef = useRef<HTMLDivElement>(null);

  const scriptLines = useMemo(() => dynamicScript.split("\n"), [dynamicScript]);
  const executableLines = useMemo(
    () =>
      scriptLines
        .map((l, i) => ({ l, i }))
        .filter(({ l }) => l.trim().length > 0 && !l.trim().startsWith("#"))
        .map(({ i }) => i),
    [scriptLines],
  );

  // Elapsed timer
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setElapsed(Date.now() - startedAt.current), 250);
    return () => clearInterval(t);
  }, [running]);

  // Auto-scroll feed
  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [feed.length]);

  // Auto-scroll active line into view
  useEffect(() => {
    activeLineRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeLine]);

  const sortedBeliefs = useMemo(
    () => [...beliefs].sort((a, b) => b.prob - a.prob),
    [beliefs],
  );
  const leadingKey = sortedBeliefs[0]?.key;

  const totalViolations = findings.reduce((s, f) => s + f.count, 0);
  const violationCats = findings.filter((f) => f.state === "violation").length;

  const handleSubmitPrompt = async () => {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    setSubmittedPrompt(trimmed);
    setPrompt("");
    setFeed([]);
    setBeliefs([]);
    setFindings(INITIAL_FINDINGS);
    setApproved(false);
    setAborted(false);
    setConfidence(0);
    setEntropy(entropyStart);
    setCompletedLines(new Set());
    setActiveLine(null);
    setDynamicPlan([]);
    setDynamicScript("");
    setLoadingPlan(true);

    try {
      const res = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: trimmed }),
      });
      if (res.ok) {
        const data = await res.json();
        setDynamicPlan(data.plan || []);
        setDynamicScript(data.script || "");
      }
    } catch (e) {
      console.error("Failed to fetch plan:", e);
    } finally {
      setLoadingPlan(false);
    }
  };

  const handleApproveExecute = async () => {
    setApproved(true);
    startedAt.current = Date.now();
    setRunning(true);

    try {
      const res = await fetch("/api/incident", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: submittedPrompt }),
      });

      if (!res.body) return;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          setRunning(false);
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const tLine = line.trim();
          if (!tLine) continue;

          if (tLine.startsWith("data: ")) {
            try {
              const data = JSON.parse(tLine.slice(6));

              if (data.type === "step") {
                if (data.step_log && data.step_log.length > 0) {
                  const msg = data.step_log[data.step_log.length - 1];
                  const rawWorker = data.current_worker?.toLowerCase() || "master";
                  const agentKey: AgentKey = AGENT_META[rawWorker as AgentKey] ? (rawWorker as AgentKey) : "master";
                  
                  setFeed((prev) => [
                    ...prev,
                    {
                      id: prev.length,
                      agent: agentKey,
                      ts: nowStamp(),
                      msg: msg,
                      status: data.step_log.some((s: string) => s.toLowerCase().includes("fail") || s.toLowerCase().includes("error")) ? "fail" : "ok",
                    },
                  ]);
                }
                if (data.confidence_score !== undefined) {
                  setConfidence(data.confidence_score * 100);
                }
                if (data.bayesian_entropy !== undefined) {
                  setEntropy(data.bayesian_entropy);
                }
                if (data.bayesian_beliefs && Object.keys(data.bayesian_beliefs).length > 0) {
                  const newBeliefs: Belief[] = Object.entries(data.bayesian_beliefs).map(([k, v]) => ({
                    key: k,
                    label: k.replace(/_/g, " ").replace(/\\b\\w/g, (l) => l.toUpperCase()),
                    prob: (v as number) * 100,
                  }));
                  setBeliefs(newBeliefs);
                }
              } else if (data.type === "complete") {
                setRunning(false);
              } else if (data.type === "killed") {
                setRunning(false);
                setAborted(true);
              }
            } catch (e) {
              console.error("Parse error:", e);
            }
          }
        }
      }
    } catch (e) {
      console.error("Stream error:", e);
      setRunning(false);
    }
  };

  return (
    <div className="min-h-screen bg-genesis-bg font-mono text-genesis-text genesis-grid-bg">
      {/* TOP BAR */}
      <header className="flex items-center justify-between border-b border-genesis-border bg-genesis-bg/90 px-5 py-3 backdrop-blur">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2.5">
            <div className="relative">
              <div className="h-7 w-7 rotate-45 border border-genesis-cyan bg-genesis-cyan/10 shadow-[0_0_16px_rgba(0,212,255,0.5)]" />
              <div className="absolute inset-1.5 rotate-45 bg-genesis-cyan" />
            </div>
            <div className="flex flex-col leading-none">
              <span className="text-sm font-bold tracking-[0.32em] genesis-glow-text text-genesis-cyan">
                GENESIS
              </span>
              <span className="mt-0.5 text-[9px] uppercase tracking-[0.3em] text-genesis-muted">
                Autonomous Ops · v4.1.0
              </span>
            </div>
          </div>
          <div className="hidden h-8 w-px bg-genesis-border md:block" />
          <div className="hidden flex-col leading-none md:flex">
            <span className="text-[9px] uppercase tracking-widest text-genesis-muted">Incident</span>
            <span className="mt-1 text-sm font-semibold text-genesis-text">
              {submittedPrompt ? submittedPrompt.slice(0, 32) + (submittedPrompt.length > 32 ? "…" : "") : "GEN-2148-EU"}
            </span>
          </div>
          <div className="hidden flex-col leading-none md:flex">
            <span className="text-[9px] uppercase tracking-widest text-genesis-muted">Elapsed</span>
            <span className="mt-1 text-sm font-semibold tabular-nums text-genesis-text">
              {formatElapsed(elapsed)}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-5">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                running ? "bg-genesis-green genesis-pulse-dot" : "bg-genesis-muted"
              }`}
            />
            <span className="text-[10px] uppercase tracking-[0.25em] text-genesis-muted">
              {running ? (approved ? "Investigating" : submittedPrompt ? "Awaiting Approval" : "Standby") : "Complete"}
            </span>
          </div>
          <div className="flex flex-col items-end leading-none">
            <span className="text-[9px] uppercase tracking-widest text-genesis-muted">Confidence</span>
            <span className="mt-1 text-lg font-bold tabular-nums genesis-glow-text text-genesis-cyan">
              {confidence.toFixed(1)}%
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              setAborted(true);
              setRunning(false);
            }}
            className="group flex items-center gap-2 border border-genesis-red/60 bg-genesis-red/10 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-genesis-red transition hover:bg-genesis-red/20 hover:shadow-[0_0_16px_rgba(255,68,102,0.5)]"
          >
            <Power className="h-3.5 w-3.5" />
            Kill Switch
          </button>
        </div>
      </header>

      {/* PROMPT BAR */}
      <div className="border-b border-genesis-border bg-genesis-surface/80 px-5 py-3">
        <div className="flex items-center gap-3">
          <span className="select-none text-genesis-cyan text-lg leading-none">❯</span>
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmitPrompt();
            }}
            placeholder={submittedPrompt ? "Enter new investigation prompt…" : "Describe the incident or issue to investigate…"}
            className="flex-1 bg-transparent text-[13px] leading-relaxed text-genesis-text placeholder:text-genesis-dim/40 outline-none"
            spellCheck={false}
            autoComplete="off"
          />
          <button
            type="button"
            onClick={handleSubmitPrompt}
            disabled={!prompt.trim()}
            className="flex items-center gap-1.5 border border-genesis-cyan/60 bg-genesis-cyan/10 px-4 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-genesis-cyan transition hover:bg-genesis-cyan/20 hover:shadow-[0_0_16px_rgba(0,212,255,0.45)] disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <Brain className="h-3 w-3" />
            Deploy
          </button>
        </div>
        {submittedPrompt && (
          <div className="mt-2 text-[10px] uppercase tracking-widest text-genesis-muted">
            Active mission: <span className="text-genesis-cyan">{submittedPrompt}</span>
          </div>
        )}
      </div>

      {/* GRID */}
      <main className="grid gap-3 p-3 lg:grid-cols-2 lg:grid-rows-2 lg:h-[calc(100vh-156px)]">
        {/* TOP LEFT — Feed */}
        <PanelFrame
          title="Live Investigation Feed"
          meta={`${feed.length.toString().padStart(3, "0")} events`}
        >
          <div ref={feedRef} className="h-full overflow-y-auto px-4 py-3">
            {feed.length === 0 && (
              <div className="flex h-full items-center justify-center text-[11px] uppercase tracking-widest text-genesis-muted">
                <CircleDot className="mr-2 h-3 w-3 animate-pulse" />
                {submittedPrompt ? "Awaiting plan approval to begin stream…" : "Enter a prompt above to initiate an investigation…"}
              </div>
            )}
            <ol className="relative space-y-2.5">
              {feed.map((step) => {
                const meta = AGENT_META[step.agent];
                const Icon = meta.icon;
                const statusColor =
                  step.status === "ok"
                    ? "border-l-genesis-green text-genesis-green"
                    : step.status === "fail"
                      ? "border-l-genesis-red text-genesis-red"
                      : "border-l-genesis-amber text-genesis-amber";
                return (
                  <li
                    key={step.id}
                    className={`genesis-slide-up flex items-start gap-3 border-l-2 ${statusColor} bg-genesis-elevated/40 px-3 py-2`}
                  >
                    <Icon className={`mt-0.5 h-4 w-4 flex-shrink-0 ${meta.color}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest">
                        <span className={meta.color}>{meta.label}</span>
                        <span className="text-genesis-dim">·</span>
                        <span className="tabular-nums text-genesis-muted">{step.ts}</span>
                      </div>
                      <p className="mt-0.5 text-[12px] leading-snug text-genesis-text">{step.msg}</p>
                    </div>
                    <span
                      className={`mt-1 text-[10px] uppercase tracking-widest ${
                        step.status === "ok"
                          ? "text-genesis-green"
                          : step.status === "fail"
                            ? "text-genesis-red"
                            : "text-genesis-amber"
                      }`}
                    >
                      {step.status === "ok" ? "OK" : step.status === "fail" ? "FAIL" : "…"}
                    </span>
                  </li>
                );
              })}
            </ol>
          </div>
        </PanelFrame>

        {/* TOP RIGHT — Beliefs */}
        <PanelFrame
          title="Bayesian Belief Distribution"
          meta={`${sortedBeliefs.length} hypotheses`}
        >
          <div className="flex h-full flex-col p-4">
            <div className="flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={sortedBeliefs}
                  layout="vertical"
                  margin={{ top: 4, right: 40, left: 0, bottom: 4 }}
                >
                  <XAxis type="number" hide domain={[0, 100]} />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={150}
                    tick={{ fill: "#5a7a96", fontSize: 10, fontFamily: "JetBrains Mono" }}
                    axisLine={{ stroke: "#173049" }}
                    tickLine={false}
                  />
                  <Bar dataKey="prob" radius={[0, 0, 0, 0]} barSize={14} animationDuration={600}>
                    {sortedBeliefs.map((b) => (
                      <Cell
                        key={b.key}
                        fill={b.key === leadingKey ? "#00d4ff" : "#173049"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 flex items-end justify-between border-t border-genesis-border pt-3">
              <div>
                <div className="text-[9px] uppercase tracking-widest text-genesis-muted">Leading Hypothesis</div>
                <div className="mt-1 text-sm font-semibold text-genesis-cyan">
                  {sortedBeliefs[0]?.label} · {sortedBeliefs[0]?.prob.toFixed(1)}%
                </div>
              </div>
              <div className="text-right">
                <div className="text-[9px] uppercase tracking-widest text-genesis-muted">Uncertainty</div>
                <div className="mt-1 font-mono text-sm tabular-nums text-genesis-text">
                  {entropyStart.toFixed(1)} bits
                  <span className="mx-1 text-genesis-cyan">→</span>
                  <span className="text-genesis-green">{entropy.toFixed(1)} bits</span>
                </div>
              </div>
            </div>
          </div>
        </PanelFrame>

        {/* BOTTOM LEFT — Plan / Script */}
        <PanelFrame
          title={approved ? "Script Execution · investigate.py" : "Proposed Investigation Plan"}
          meta={
            approved
              ? activeLine !== null
                ? `PC → L${String(activeLine + 1).padStart(2, "0")} · ${completedLines.size}/${executableLines.length}`
                : `HALTED · ${completedLines.size}/${executableLines.length}`
              : aborted
                ? "ABORTED"
                : "PENDING APPROVAL"
          }
        >
          <div className="flex h-full flex-col">
            {!approved && !aborted && (
              <>
                <ol className="flex-1 space-y-2 overflow-y-auto px-4 py-3">
                  {loadingPlan ? (
                    <div className="flex h-full items-center justify-center text-[11px] uppercase tracking-widest text-genesis-muted">
                      <CircleDot className="mr-2 h-3 w-3 animate-pulse" />
                      Generating Investigation Plan...
                    </div>
                  ) : dynamicPlan.map((step, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-3 border border-genesis-border/60 bg-genesis-elevated/40 px-3 py-2"
                    >
                      <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center border border-genesis-cyan/40 bg-genesis-cyan/5 text-[11px] font-bold text-genesis-cyan">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="text-[12px] leading-relaxed text-genesis-text">{step}</span>
                    </li>
                  ))}
                </ol>
                <div className="grid grid-cols-2 gap-2 border-t border-genesis-border p-3">
                  <button
                    type="button"
                    onClick={() => setAborted(true)}
                    className="flex items-center justify-center gap-2 border border-genesis-red bg-genesis-red/10 py-3 text-[11px] font-bold uppercase tracking-[0.25em] text-genesis-red transition hover:bg-genesis-red/20"
                  >
                    <XCircle className="h-4 w-4" />
                    Abort
                  </button>
                  <button
                    type="button"
                    onClick={handleApproveExecute}
                    disabled={loadingPlan || dynamicPlan.length === 0}
                    className="flex items-center justify-center gap-2 border border-genesis-green bg-genesis-green/15 py-3 text-[11px] font-bold uppercase tracking-[0.25em] text-genesis-green shadow-[0_0_20px_rgba(0,255,136,0.25)] transition hover:bg-genesis-green/25 hover:shadow-[0_0_28px_rgba(0,255,136,0.45)]"
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Approve & Execute
                  </button>
                </div>
              </>
            )}
            {aborted && (
              <div className="flex flex-1 flex-col items-center justify-center gap-2 text-genesis-red">
                <AlertTriangle className="h-8 w-8" />
                <div className="text-sm font-bold uppercase tracking-[0.25em]">Investigation Aborted</div>
                <div className="text-[11px] text-genesis-muted">Operator intervention recorded · GEN-2148</div>
              </div>
            )}
            {approved && (
              <pre className="flex-1 overflow-auto bg-[#070b14] p-0 text-[11px] leading-relaxed">
                <code className="block py-2">
                  {scriptLines.map((line, i) => {
                    const isActive = activeLine === i;
                    const isDone = completedLines.has(i);
                    return (
                      <div
                        key={i}
                        ref={isActive ? activeLineRef : undefined}
                        className={`group relative flex gap-3 px-3 transition-colors ${
                          isActive
                            ? "bg-genesis-cyan/10 shadow-[inset_3px_0_0_var(--color-genesis-cyan)]"
                            : isDone
                              ? "opacity-60"
                              : "opacity-90"
                        }`}
                      >
                        <span
                          className={`select-none text-right tabular-nums ${
                            isActive ? "text-genesis-cyan" : "text-genesis-dim"
                          }`}
                          style={{ width: 28 }}
                        >
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        <span className={`w-3 select-none ${isActive ? "text-genesis-cyan genesis-pulse-dot" : "text-transparent"}`}>
                          ▶
                        </span>
                        <span className="flex-1 whitespace-pre">{colorize(line || " ")}</span>
                        {isDone && !isActive && (
                          <span className="select-none text-[10px] text-genesis-green">✓</span>
                        )}
                      </div>
                    );
                  })}
                </code>
              </pre>
            )}
          </div>
        </PanelFrame>

        {/* BOTTOM RIGHT — Findings */}
        <PanelFrame
          title="Compliance Findings"
          meta={`${totalViolations} violations · ${violationCats}/5 categories`}
        >
          <div className="flex h-full flex-col p-3">
            <div className="grid flex-1 grid-cols-1 gap-2 sm:grid-cols-2">
              {findings.map((f) => {
                const stateMeta =
                  f.state === "violation"
                    ? {
                        ring: "border-genesis-red/70 bg-genesis-red/10 shadow-[0_0_18px_rgba(255,68,102,0.25)]",
                        text: "text-genesis-red",
                        label: "VIOLATION",
                        Icon: AlertTriangle,
                      }
                    : f.state === "clean"
                      ? {
                          ring: "border-genesis-green/60 bg-genesis-green/5",
                          text: "text-genesis-green",
                          label: "CLEAN",
                          Icon: CheckCircle2,
                        }
                      : {
                          ring: "border-genesis-border bg-genesis-elevated/40",
                          text: "text-genesis-muted",
                          label: "PENDING",
                          Icon: CircleDot,
                        };
                const Icon = stateMeta.Icon;
                return (
                  <div
                    key={f.key}
                    className={`genesis-slide-up flex flex-col justify-between border p-3 transition-colors ${stateMeta.ring}`}
                  >
                    <div className="flex items-start justify-between">
                      <Icon className={`h-4 w-4 ${stateMeta.text}`} />
                      {f.count > 0 && (
                        <span className="border border-genesis-red/60 bg-genesis-red/20 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-genesis-red">
                          ×{f.count}
                        </span>
                      )}
                    </div>
                    <div>
                      <div className="text-[12px] font-semibold text-genesis-text">{f.label}</div>
                      <div className={`mt-0.5 text-[9px] uppercase tracking-widest ${stateMeta.text}`}>
                        {stateMeta.label}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-genesis-border pt-3">
              <span className="text-[10px] uppercase tracking-widest text-genesis-muted">Summary</span>
              <span className="text-[12px] text-genesis-text">
                <span className="font-bold text-genesis-red">{totalViolations} violations</span>
                <span className="text-genesis-muted"> across </span>
                <span className="font-bold text-genesis-amber">{violationCats} categories</span>
              </span>
            </div>
          </div>
        </PanelFrame>
      </main>

      {/* BOTTOM BAR */}
      <footer className="flex items-center justify-between border-t border-genesis-border bg-genesis-bg/90 px-5 py-2.5 text-[10px] uppercase tracking-[0.25em] text-genesis-muted">
        <div className="flex items-center gap-2">
          <Activity className="h-3 w-3 text-genesis-cyan" />
          <span>Telemetry uplink stable · 14ms RTT</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-genesis-muted">Powered by</span>
          <span className="font-bold text-genesis-text">Gemini</span>
          <span className="text-genesis-dim">·</span>
          <span className="font-bold text-genesis-text">MongoDB</span>
          <span className="text-genesis-dim">·</span>
          <span className="font-bold text-genesis-text">Dynatrace</span>
        </div>
      </footer>
    </div>
  );
}

function colorize(line: string): React.ReactNode {
  // Comments
  if (line.trim().startsWith("#")) {
    return <span className="text-genesis-muted">{line}</span>;
  }
  const tokens: React.ReactNode[] = [];
  const regex = /(\b(?:import|from|async|await|def|return|if|else|for|in)\b)|(\b(?:True|False|None)\b)|("[^"]*"|'[^']*')|(\b\d+\.?\d*\b)|(\b[a-zA-Z_][\w]*(?=\())/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = regex.exec(line))) {
    if (m.index > last) tokens.push(<span key={key++}>{line.slice(last, m.index)}</span>);
    if (m[1]) tokens.push(<span key={key++} className="text-genesis-purple">{m[0]}</span>);
    else if (m[2]) tokens.push(<span key={key++} className="text-genesis-amber">{m[0]}</span>);
    else if (m[3]) tokens.push(<span key={key++} className="text-genesis-green">{m[0]}</span>);
    else if (m[4]) tokens.push(<span key={key++} className="text-genesis-amber">{m[0]}</span>);
    else if (m[5]) tokens.push(<span key={key++} className="text-genesis-cyan">{m[0]}</span>);
    last = m.index + m[0].length;
  }
  if (last < line.length) tokens.push(<span key={key++} className="text-genesis-text">{line.slice(last)}</span>);
  return <>{tokens}</>;
}
