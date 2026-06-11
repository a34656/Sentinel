"""
tools/bayesian_selector.py — Bayesian Active Investigation Selector

This is the research contribution of Project Genesis (BAIRA).

The problem with greedy LLM-guided agents:
    The Master asks "what should I do next?" and the model picks based on
    what seems intuitively reasonable. There is no formal criterion for
    action selection — it's pattern matching.

The BAIRA approach:
    Frame incident investigation as a POMDP where:
    - Hidden state S = the true root cause category
    - Actions A = tool calls (analyst, engineer, scout, ...)
    - Observations O = tool outputs
    - Belief state B = probability distribution over S

    At each step, select the action that maximises expected information gain
    (reduces entropy over B the most), weighted by cost.

    Formally: action* = argmax_a [ H(B) - E[H(B' | a, o)] ] / cost(a)
    where H is Shannon entropy and cost is token/latency cost.

How it integrates with Genesis:
    - The BayesianSelector is called by master.py BEFORE invoking the LLM
    - It returns a ranked list of suggested actions with expected info gain
    - This ranking is injected into the Master's context as a hint
    - The Master can follow or override the hint — it's advisory, not mandatory
    - After each observation, the belief state is updated with Bayes' rule

This design means:
    - The Bayesian selector costs almost nothing (pure Python, no LLM call)
    - It degrades gracefully — if disabled, master.py works exactly as before
    - We can measure empirically whether Bayesian-guided runs use fewer steps

Research comparison:
    Baseline:  vanilla master.py (greedy LLM selection)
    Treatment: master.py + BayesianSelector hints
    Metric:    steps to correct root cause, false positive auto-fix rate
"""

import math
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


# ── Root cause taxonomy ───────────────────────────────────────────────────────
# These are the hidden states S in the POMDP.
# Each category has a prior probability (from historical incident data).
# Priors sum to 1.0 and can be updated from your incident history.

ROOT_CAUSE_CATEGORIES = {
    "billing_spike":       0.18,   # Unexpected cost increase
    "resource_exhaustion": 0.22,   # CPU/memory/connection pool exhausted
    "misconfiguration":    0.20,   # Wrong env var, config change, IAM policy
    "dependency_failure":  0.15,   # Downstream service, DB, external API
    "network_issue":       0.10,   # DNS, routing, firewall, latency
    "security_event":      0.08,   # Unauthorized access, exposed credentials
    "deployment_bug":      0.07,   # Bad release, regression
}

# ── Action definitions ────────────────────────────────────────────────────────
# Each action has:
#   - likelihood_updates: P(observation reveals category | action taken)
#     i.e. how much does this action help distinguish each root cause?
#   - token_cost: relative cost (1.0 = baseline)
#   - latency_ms: approximate expected latency

@dataclass
class ActionProfile:
    name: str
    # For each root cause category: P(this action produces informative signal | that is the cause)
    # Higher = this action is more diagnostic for that cause
    diagnostic_power: dict[str, float]
    token_cost: float     # relative (1.0 = one analyst call)
    latency_ms: int       # approximate

ACTION_PROFILES = [
    ActionProfile(
        name="analyst",
        diagnostic_power={
            "billing_spike":       0.90,   # Cost Explorer is definitive for billing
            "resource_exhaustion": 0.60,   # CloudWatch shows resource metrics
            "misconfiguration":    0.20,
            "dependency_failure":  0.30,
            "network_issue":       0.20,
            "security_event":      0.10,
            "deployment_bug":      0.10,
        },
        token_cost=0.5,
        latency_ms=2000,
    ),
    ActionProfile(
        name="engineer",
        diagnostic_power={
            "billing_spike":       0.50,   # Can query Cost Explorer directly
            "resource_exhaustion": 0.80,   # Can inspect processes, memory, connections
            "misconfiguration":    0.70,   # Can read config files, env vars
            "dependency_failure":  0.75,   # Can test connectivity, query APIs
            "network_issue":       0.65,   # Can run network diagnostics
            "security_event":      0.55,   # Can check IAM policies, audit logs
            "deployment_bug":      0.70,   # Can read logs, test endpoints
        },
        token_cost=1.5,    # Costs more — involves script generation + sandbox
        latency_ms=8000,
    ),
    ActionProfile(
        name="scout",
        diagnostic_power={
            "billing_spike":       0.20,
            "resource_exhaustion": 0.30,
            "misconfiguration":    0.60,   # Reading docs helps identify misconfig
            "dependency_failure":  0.50,   # Reading API docs, release notes
            "network_issue":       0.40,
            "security_event":      0.45,
            "deployment_bug":      0.55,   # Reading release notes, changelogs
        },
        token_cost=0.8,
        latency_ms=5000,
    ),
    ActionProfile(
        name="policy_guard",
        diagnostic_power={
            "billing_spike":       0.05,
            "resource_exhaustion": 0.05,
            "misconfiguration":    0.10,
            "dependency_failure":  0.05,
            "network_issue":       0.05,
            "security_event":      0.30,   # Checking IAM policies is relevant here
            "deployment_bug":      0.05,
        },
        token_cost=0.2,
        latency_ms=500,
    ),
]

ACTION_MAP = {a.name: a for a in ACTION_PROFILES}


# ── Belief state ──────────────────────────────────────────────────────────────

@dataclass
class BeliefState:
    """
    Probability distribution over root cause categories.
    Starts at prior and updates with each observation.
    """
    beliefs: dict[str, float] = field(default_factory=lambda: dict(ROOT_CAUSE_CATEGORIES))
    observations: list[str] = field(default_factory=list)
    step: int = 0

    def entropy(self) -> float:
        """Shannon entropy of the current belief distribution. Higher = more uncertain."""
        h = 0.0
        for p in self.beliefs.values():
            if p > 0:
                h -= p * math.log2(p)
        return h

    def top_hypothesis(self) -> tuple[str, float]:
        """Return the most likely root cause and its probability."""
        best = max(self.beliefs.items(), key=lambda x: x[1])
        return best

    def update(self, action_name: str, observation_keywords: list[str]) -> None:
        """
        Bayesian update of beliefs given an observation.

        P(cause | observation) ∝ P(observation | cause) × P(cause)

        We approximate P(observation | cause) using keyword matching:
        - Keywords that strongly suggest a cause increase its posterior
        - Keywords that suggest other causes decrease the target cause
        """
        if action_name not in ACTION_MAP:
            return

        profile = ACTION_MAP[action_name]
        observation_text = " ".join(observation_keywords).lower()

        # Likelihood function: does this observation match the diagnostic pattern?
        likelihoods = {}
        for cause in self.beliefs:
            base_diagnostic = profile.diagnostic_power[cause]
            # Boost if observation contains cause-specific keywords
            keyword_match = _keyword_match_score(observation_text, cause)
            likelihoods[cause] = base_diagnostic * (0.5 + keyword_match)

        # Bayesian update
        unnormalised = {c: self.beliefs[c] * likelihoods[c] for c in self.beliefs}
        total = sum(unnormalised.values())
        if total > 0:
            self.beliefs = {c: v / total for c, v in unnormalised.items()}

        self.observations.append(f"[{action_name}] {', '.join(observation_keywords[:5])}")
        self.step += 1

        top_cause, top_prob = self.top_hypothesis()
        logger.debug(
            f"[Bayesian] Belief updated. Top: {top_cause} ({top_prob:.2f}) | "
            f"Entropy: {self.entropy():.3f}"
        )


# ── Selector ──────────────────────────────────────────────────────────────────

@dataclass
class BayesianSelector:
    """
    Selects the next action to maximise expected information gain per token cost.
    """
    belief_state: BeliefState = field(default_factory=BeliefState)
    already_used: list[str] = field(default_factory=list)

    def expected_info_gain(self, action: ActionProfile) -> float:
        """
        Estimate how much entropy reduction we expect if we take this action.

        E[ΔH] ≈ H(current) - E[H(posterior | action)]

        We approximate the posterior by assuming the action reveals the
        most likely cause with probability = diagnostic_power[top_cause].
        """
        current_entropy = self.belief_state.entropy()
        top_cause, _ = self.belief_state.top_hypothesis()

        # Simulate: if action is taken and confirms top_cause
        sim_beliefs = dict(self.belief_state.beliefs)
        diagnostic_p = action.diagnostic_power[top_cause]

        # Posterior if action confirms the top hypothesis
        sim_beliefs[top_cause] = min(0.99, sim_beliefs[top_cause] * (1 + diagnostic_p))
        total = sum(sim_beliefs.values())
        sim_beliefs = {c: v / total for c, v in sim_beliefs.items()}

        # Entropy of simulated posterior
        sim_entropy = -sum(p * math.log2(p) for p in sim_beliefs.values() if p > 0)

        # Expected entropy reduction, discounted by action cost
        delta_h = max(0, current_entropy - sim_entropy)
        return delta_h / max(action.token_cost, 0.1)

    def rank_actions(
        self,
        available: Optional[list[str]] = None,
        exclude_used: bool = True,
    ) -> list[tuple[str, float]]:
        """
        Return actions ranked by expected information gain / cost.
        Higher score = better next action.
        """
        candidates = available or list(ACTION_MAP.keys())

        if exclude_used and len(self.already_used) < len(candidates) - 1:
            # Don't re-use the same action twice in a row (diminishing returns)
            # Unless all actions have been tried
            last_used = self.already_used[-1] if self.already_used else None
            candidates = [a for a in candidates if a != last_used]

        ranked = []
        for name in candidates:
            if name not in ACTION_MAP:
                continue
            profile = ACTION_MAP[name]
            score = self.expected_info_gain(profile)
            ranked.append((name, round(score, 4)))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    def suggest(self, context: str = "") -> str:
        """
        Return a formatted suggestion string to inject into the Master's context.
        The Master reads this and can follow or override it.
        """
        top_cause, top_prob = self.belief_state.top_hypothesis()
        entropy = self.belief_state.entropy()
        ranked = self.rank_actions()

        lines = [
            "\n--- BAYESIAN INVESTIGATION ADVISOR ---",
            f"Current entropy: {entropy:.3f} (0=certain, {math.log2(len(ROOT_CAUSE_CATEGORIES)):.1f}=max uncertain)",
            f"Leading hypothesis: {top_cause} ({top_prob*100:.0f}% probability)",
            f"Confidence assessment: {'Converging' if entropy < 1.5 else 'Still uncertain — more data needed'}",
            "",
            "Recommended next actions (by expected information gain / cost):",
        ]
        for i, (action, score) in enumerate(ranked[:3], 1):
            lines.append(f"  {i}. {action} (info gain score: {score:.3f})")

        lines.append("You may override this recommendation if you have specific evidence that changes the prior.")
        lines.append("--- END BAYESIAN ADVISOR ---")

        return "\n".join(lines)

    def record_action(self, action_name: str, output_keywords: list[str]) -> None:
        """Call after each worker returns to update beliefs."""
        self.belief_state.update(action_name, output_keywords)
        self.already_used.append(action_name)


# ── Keyword match scoring ─────────────────────────────────────────────────────

_CAUSE_KEYWORDS = {
    "billing_spike":       ["cost", "bill", "charge", "spend", "usd", "dollar", "increase", "pricing"],
    "resource_exhaustion": ["cpu", "memory", "oom", "exhausted", "full", "limit", "throttl", "pool"],
    "misconfiguration":    ["config", "env", "variable", "wrong", "invalid", "missing", "format"],
    "dependency_failure":  ["timeout", "connection refused", "unavailable", "unreachable", "downstream"],
    "network_issue":       ["dns", "routing", "packet", "latency", "network", "firewall", "port"],
    "security_event":      ["unauthorized", "forbidden", "403", "iam", "permission", "credential", "token"],
    "deployment_bug":      ["deploy", "release", "regression", "version", "rollback", "commit"],
}

def _keyword_match_score(text: str, cause: str) -> float:
    """Score 0-1: how many cause-specific keywords appear in the text."""
    keywords = _CAUSE_KEYWORDS.get(cause, [])
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw in text)
    return min(1.0, hits / max(len(keywords) * 0.3, 1))


# ── Extract keywords from tool output ────────────────────────────────────────

def extract_keywords_from_output(output: str, stderr: str = "") -> list[str]:
    """
    Extract signal keywords from a worker's output for belief state update.
    Called by master.py after each worker returns.
    """
    combined = (output + " " + stderr).lower()
    all_keywords = []
    for keywords in _CAUSE_KEYWORDS.values():
        all_keywords.extend(keywords)
    return [kw for kw in all_keywords if kw in combined]
