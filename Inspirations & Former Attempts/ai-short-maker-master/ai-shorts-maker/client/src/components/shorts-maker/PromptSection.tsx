import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { WhisperModelSelect } from "@/components/WhisperModelSelect"

interface PromptSectionProps {
  prompt: string
  onPromptChange: (value: string) => void
  whisperModel: string
  onWhisperModelChange: (value: string) => void
  durationMin: string
  onDurationMinChange: (value: string) => void
  durationMax: string
  onDurationMaxChange: (value: string) => void
  isGlobalPrompt?: boolean
  onGlobalPromptChange?: (value: boolean) => void
  disabled?: boolean
}

export function PromptSection({
  prompt,
  onPromptChange,
  whisperModel,
  onWhisperModelChange,
  durationMin,
  onDurationMinChange,
  durationMax,
  onDurationMaxChange,
  isGlobalPrompt,
  onGlobalPromptChange,
  disabled
}: PromptSectionProps) {
  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Label>Prompt for Analysis</Label>
          {onGlobalPromptChange && (
            <div className="flex items-center gap-2">
              <Switch
                checked={isGlobalPrompt}
                onCheckedChange={onGlobalPromptChange}
                disabled={disabled}
              />
              <Label>Use Global Prompt</Label>
            </div>
          )}
        </div>
        <Textarea
          className="min-h-[100px] resize-y"
          placeholder="Enter prompt to analyze and clip the videos..."
          value={prompt}
          onChange={(e) => onPromptChange(e.target.value)}
          disabled={disabled || isGlobalPrompt}
        />
      </div>

      <WhisperModelSelect
        value={whisperModel}
        onValueChange={onWhisperModelChange}
        label="Initial Video Analysis Whisper Model"
        disabled={disabled}
      />

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label>Minimum Duration (seconds)</Label>
          <Input
            type="number"
            min="15"
            max="180"
            step="1"
            value={durationMin}
            onChange={(e) => onDurationMinChange(e.target.value)}
            disabled={disabled}
          />
        </div>
        <div className="space-y-2">
          <Label>Maximum Duration (seconds)</Label>
          <Input
            type="number"
            min="15"
            max="180"
            step="1"
            value={durationMax}
            onChange={(e) => onDurationMaxChange(e.target.value)}
            disabled={disabled}
          />
        </div>
      </div>
    </div>
  )
}