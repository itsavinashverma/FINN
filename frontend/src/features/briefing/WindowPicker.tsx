import { Segmented } from "@/components/ui/Segmented"

export type WindowOption = "24" | "72" | "168" | "720"

export const WINDOW_OPTIONS: { value: WindowOption; label: string }[] = [
  { value: "24", label: "24h" },
  { value: "72", label: "3d" },
  { value: "168", label: "7d" },
  { value: "720", label: "30d" },
]

export function WindowPicker({ value, onChange }: { value: WindowOption; onChange: (v: WindowOption) => void }) {
  return <Segmented options={WINDOW_OPTIONS} value={value} onChange={onChange} />
}
