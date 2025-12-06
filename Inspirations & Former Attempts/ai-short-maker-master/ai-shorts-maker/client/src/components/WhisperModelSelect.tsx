import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { WHISPER_MODELS } from "@/lib/constants"
import { Label } from "./ui/label"

interface WhisperModelSelectProps {
  value: string
  onValueChange: (value: string) => void
  label: string
  disabled?: boolean
}

export function WhisperModelSelect({ value, onValueChange, label, disabled }: WhisperModelSelectProps) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <Select value={value} onValueChange={onValueChange} disabled={disabled}>
        <SelectTrigger>
          <SelectValue placeholder="Select Whisper model" />
        </SelectTrigger>
        <SelectContent>
          {WHISPER_MODELS.map((model) => (
            <SelectItem key={model.value} value={model.value}>
              {model.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}