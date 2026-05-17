import { createFileRoute } from "@tanstack/react-router";
import GenesisDashboard from "@/components/genesis/GenesisDashboard";

export const Route = createFileRoute("/")({
  component: GenesisDashboard,
  head: () => ({
    meta: [
      { title: "Genesis · Autonomous Ops Mission Control" },
      {
        name: "description",
        content:
          "Genesis mission control: live agent feed, Bayesian belief tracking, approval-gated execution, and compliance findings for autonomous incident response.",
      },
    ],
  }),
});
