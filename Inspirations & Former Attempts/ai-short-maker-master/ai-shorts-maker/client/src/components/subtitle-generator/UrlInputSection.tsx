import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { VideoUploadZone } from "@/components/VideoUploadZone"
import type { VideoItem } from "@/types/video"

interface UrlInputSectionProps {
  onUrlAdd: (urls: string[]) => void
  onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void
  loading?: boolean
}

export function UrlInputSection({ onUrlAdd, onFileChange, loading }: UrlInputSectionProps) {
  const [urlInput, setUrlInput] = useState("")

  const handleUrlAdd = () => {
    const urls = urlInput.split("\n").filter(url => url.trim())
    if (urls.length > 0) {
      onUrlAdd(urls)
      setUrlInput("")
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Add Videos</Label>
        <div className="grid gap-4">
          <VideoUploadZone
            onFileChange={onFileChange}
            id="video-upload"
            label="Drop video files here or click to browse"
          />

          <div className="space-y-2">
            <Label>Or add video URLs</Label>
            <div className="flex gap-2">
              <Textarea
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="Enter video URLs (one per line)"
                className="min-h-[100px] resize-y"
                disabled={loading}
              />
              <Button
                type="button"
                variant="secondary"
                className="shrink-0 hover:scale-105 transition-transform"
                onClick={handleUrlAdd}
                disabled={loading}
              >
                {loading ? "Adding..." : "Add URLs"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}