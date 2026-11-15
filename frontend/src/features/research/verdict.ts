import type { Verdict } from "@/lib/types"

export const VERDICT_LABEL: Record<Verdict, string> = {
  met: "Met",
  exceeded: "Exceeded",
  fell_short: "Fell short",
  qualitative_only: "Qualitative",
  pending: "Pending",
  no_guidance: "No guidance given",
  no_evidence: "Insufficient evidence",
}

export const VERDICT_TONE: Record<Verdict, "up" | "down" | "notable" | "neutral" | "muted"> = {
  met: "up",
  exceeded: "up",
  fell_short: "down",
  qualitative_only: "neutral",
  pending: "notable",
  no_guidance: "muted",
  no_evidence: "muted",
}
