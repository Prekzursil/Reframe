import { Button } from "@/components/ui/button"
import { Loader2 } from "lucide-react"
import type { VideoItem } from "@/types/video"

interface SubtitleFormActionsProps {
  loading: boolean
  selectedVideo: VideoItem | null
  onApplyToAll: () => void
  videoListLength: number
}

export function SubtitleFormActions({
  loading,
  selectedVideo,
  onApplyToAll,
  videoListLength
}: SubtitleFormActionsProps) {
  return (
    <div className="flex gap-2">
      <Button
        type="button"
        variant="secondary"
        className="flex-1"
        onClick={onApplyToAll}
        disabled={videoListLength === 0 || loading}
      >
        Apply Settings to All
      </Button>
      <Button
        type="submit"
        className="flex-1 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 transition-all duration-200 transform hover:scale-[1.02]"
        disabled={loading}
      >
        {loading ? (
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