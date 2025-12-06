import { Label } from "@/components/ui/label"
import { VideoUploadZone } from "@/components/VideoUploadZone"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"

interface SubtitleInputSectionProps {
  onUrlAdd: (urls: string[]) => void
  onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void
  loading?: boolean
}

export function SubtitleInputSection({
  onUrlAdd,
  onFileChange,
  loading
}: SubtitleInputSectionProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Add Subtitle Files</Label>
        <div className="grid gap-4">
          <VideoUploadZone
            onFileChange={onFileChange}
            accept=".srt"
            id="subtitle-upload"
            label="Drop SRT files here or click to browse"
          />
        </div>
      </div>
    </div>
  )
}