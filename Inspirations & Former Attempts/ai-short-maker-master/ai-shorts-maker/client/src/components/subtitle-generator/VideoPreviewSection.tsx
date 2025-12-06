import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { VideoPreview } from "@/components/VideoPreview"
import type { VideoItem } from "@/types/video"

interface VideoPreviewSectionProps {
  selectedVideo: VideoItem | null
  subtitleStyle: {
    fontSize: number
    fontColor: string
    highlightColor: string
    backgroundColor: string
    opacity: number
  }
}

export function VideoPreviewSection({ selectedVideo, subtitleStyle }: VideoPreviewSectionProps) {
  return (
    <Card className="backdrop-blur-sm bg-background/95">
      <CardHeader>
        <CardTitle>Preview</CardTitle>
        <CardDescription>
          Preview the selected video with subtitle settings
        </CardDescription>
      </CardHeader>
      <CardContent>
        {selectedVideo ? (
          <VideoPreview
            url={selectedVideo.url}
            showSubtitles={true}
            subtitleStyle={subtitleStyle}
          />
        ) : (
          <div className="aspect-[16/9] flex items-center justify-center border-2 border-dashed rounded-lg bg-card/50">
            <p className="text-muted-foreground text-center px-4">
              Select or upload a video to preview
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}