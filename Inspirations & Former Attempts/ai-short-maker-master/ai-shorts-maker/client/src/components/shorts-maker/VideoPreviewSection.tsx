import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { VideoPreview } from "@/components/VideoPreview"
import type { VideoItem } from "@/types/video"

interface VideoPreviewSectionProps {
  selectedVideo: VideoItem | null
  showSubtitles: boolean
  subtitleStyle: {
    fontSize: number
    fontColor: string
    highlightColor: string
    backgroundColor: string
    opacity: number
  }
}

export function VideoPreviewSection({
  selectedVideo,
  showSubtitles,
  subtitleStyle
}: VideoPreviewSectionProps) {
  return (
    <Card className="bg-background/95 backdrop-blur-sm border shadow-lg">
      <CardHeader>
        <CardTitle>Preview</CardTitle>
        <CardDescription>
          Preview how your shorts will look with the current settings
        </CardDescription>
      </CardHeader>
      <CardContent>
        {selectedVideo ? (
          <VideoPreview
            url={selectedVideo.url}
            showSubtitles={showSubtitles}
            subtitleStyle={subtitleStyle}
            className="shadow-xl ring-1 ring-primary/10"
          />
        ) : (
          <div className="aspect-[9/16] flex items-center justify-center border-2 border-dashed rounded-lg bg-card/50">
            <p className="text-muted-foreground text-center px-4">
              Select or upload a video to preview
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}