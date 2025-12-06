import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { FileVideo } from "lucide-react"
import { SubtitleGeneratorForm } from "@/components/subtitle-generator/SubtitleGeneratorForm"
import { VideoPreviewSection } from "@/components/subtitle-generator/VideoPreviewSection"
import { useVideoList } from "@/contexts/VideoListContext"

export function SubtitleGenerator() {
  const [isStyleOpen, setIsStyleOpen] = useState(false)
  const {
    subtitleVideos: videoList,
    setSubtitleVideos: setVideoList,
    subtitleSelectedVideo: selectedVideo,
    setSubtitleSelectedVideo: setSelectedVideo
  } = useVideoList()

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <Card className="backdrop-blur-sm bg-background/95">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileVideo className="h-6 w-6" />
            Subtitle Generator
          </CardTitle>
          <CardDescription>
            Generate accurate subtitles for your videos using AI
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SubtitleGeneratorForm
            videoList={videoList}
            setVideoList={setVideoList}
            selectedVideo={selectedVideo}
            setSelectedVideo={setSelectedVideo}
            isStyleOpen={isStyleOpen}
            setIsStyleOpen={setIsStyleOpen}
          />
        </CardContent>
      </Card>

      <div className="lg:sticky lg:top-24 space-y-4">
        <VideoPreviewSection
          selectedVideo={selectedVideo}
          subtitleStyle={{
            fontSize: 24,
            fontColor: "#FFFFFF",
            highlightColor: "#FF3B30",
            backgroundColor: "#000000",
            opacity: 80
          }}
        />
      </div>
    </div>
  )
}