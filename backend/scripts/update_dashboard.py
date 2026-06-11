import re

def update_dashboard():
    with open(r"c:\Users\KIIT0001\cloud\genesis\f2\genesis-command\src\components\genesis\GenesisDashboard.tsx", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Remove PLAN and SCRIPT constants
    content = re.sub(r'const PLAN = \[.*?\];\n\nconst SCRIPT = `.*?`;\n', '', content, flags=re.DOTALL)

    # 2. Add states
    content = content.replace(
        '  const [submittedPrompt, setSubmittedPrompt] = useState("");',
        '  const [submittedPrompt, setSubmittedPrompt] = useState("");\n  const [dynamicPlan, setDynamicPlan] = useState<string[]>([]);\n  const [dynamicScript, setDynamicScript] = useState<string>("");\n  const [loadingPlan, setLoadingPlan] = useState(false);'
    )

    # 3. Update scriptLines
    content = content.replace(
        '  const scriptLines = useMemo(() => SCRIPT.split("\\n"), []);',
        '  const scriptLines = useMemo(() => dynamicScript.split("\\n"), [dynamicScript]);'
    )

    # 4. Replace handleSubmitPrompt and add handleApproveExecute
    old_handle_submit = '''  const handleSubmitPrompt = async () => {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    setSubmittedPrompt(trimmed);
    setPrompt("");
    setFeed([]);
    setBeliefs([]);
    setFindings(INITIAL_FINDINGS);
    setApproved(true);
    setAborted(false);
    setConfidence(0);
    setEntropy(entropyStart);
    setCompletedLines(new Set());
    setActiveLine(null);
    startedAt.current = Date.now();
    setRunning(true);

    try {
      const res = await fetch("/api/incident", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: trimmed }),
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
        const lines = buffer.split("\\n");
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
                  // Map worker names to AgentKey, fallback to master
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
                    label: k.replace(/_/g, " ").replace(/\\\\b\\\\w/g, (l) => l.toUpperCase()),
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
  };'''

    new_handle_submit = '''  const handleSubmitPrompt = async () => {
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
        const lines = buffer.split("\\n");
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
                    label: k.replace(/_/g, " ").replace(/\\\\b\\\\w/g, (l) => l.toUpperCase()),
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
  };'''
    
    content = content.replace(old_handle_submit, new_handle_submit)

    # 5. Update PLAN to dynamicPlan
    content = content.replace('                  {PLAN.map((step, i) => (', '                  {loadingPlan ? (\n                    <div className="flex h-full items-center justify-center text-[11px] uppercase tracking-widest text-genesis-muted">\n                      <CircleDot className="mr-2 h-3 w-3 animate-pulse" />\n                      Generating Investigation Plan...\n                    </div>\n                  ) : dynamicPlan.map((step, i) => (')
    # Need to close the paren after the map
    # 6. Update Approve button
    content = content.replace('                    onClick={() => {\n                      setApproved(true);\n                      startedAt.current = Date.now();\n                    }}', '                    onClick={handleApproveExecute}\n                    disabled={loadingPlan || dynamicPlan.length === 0}')

    with open(r"c:\Users\KIIT0001\cloud\genesis\f2\genesis-command\src\components\genesis\GenesisDashboard.tsx", "w", encoding="utf-8") as f:
        f.write(content)

if __name__ == "__main__":
    update_dashboard()
