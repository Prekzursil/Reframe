import { Button } from "@/components/ui/button"
import { Loader2 } from "lucide-react"
import type { VideoItem } from "@/types/video"

interface FormActionsProps {
  selectedVideo: VideoItem | null
  onSaveVideoSettings: () => void
  onApplyToAll: () => void
  videoListLength: number
  isLoading?: boolean
}

export function FormActions({
  selectedVideo,
  onSaveVideoSettings,
  onApplyToAll,
  videoListLength,
  isLoading
}: FormActionsProps) {
  return (
    <div className="flex gap-2">
      <Button
        type="button"
        variant="secondary"
        className="flex-1"
        onClick={onSaveVideoSettings}
        disabled={!selectedVideo || isLoading}
      >
        Save Settings for Selected Video
      </Button>
      <Button
        type="button"
        variant="secondary"
        className="flex-1"
        onClick={onApplyToAll}
        disabled={videoListLength === 0 || isLoading}
      >
        Apply Settings to All
      </Button>
      <Button
        type="submit"
        className="flex-1 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 transition-all duration-200 transform hover:scale-[1.02]"
        disabled={isLoading}
      >
        {isLoading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Adding to Queue...
          </>
        ) : (
          "Add to Queue"
        )}
      </Button>
    </div>
  )
}