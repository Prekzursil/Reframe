import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { FileVideo } from "lucide-react"
import { VideoPreviewSection } from "@/components/shorts-maker/VideoPreviewSection"
import { FormSection } from "@/components/shorts-maker/FormSection"
import { useVideoList } from "@/contexts/VideoListContext"

export function ShortsMaker() {
  const {
    shortsMakerVideos: videoList,
    setShortsMakerVideos: setVideoList,
    shortsMakerSelectedVideo: selectedVideo,
    setShortsMakerSelectedVideo: setSelectedVideo
  } = useVideoList()
  const [isStyleOpen, setIsStyleOpen] = useState(false)

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-20">
      <Card className="backdrop-blur-sm bg-background/95 border shadow-lg">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileVideo className="h-6 w-6" />
            Shorts Maker
          </CardTitle>
          <CardDescription>
            Create engaging short videos with AI-powered analysis and stylized subtitles
          </CardDescription>
        </CardHeader>
        <CardContent>
          <FormSection
            videoList={videoList}
            setVideoList={setVideoList}
            selectedVideo={selectedVideo}
            setSelectedVideo={setSelectedVideo}
            isStyleOpen={isStyleOpen}
            setIsStyleOpen={setIsStyleOpen}
          />
        </CardContent>
      </Card>

      <div className="lg:sticky lg:top-24 h-fit">
        <VideoPreviewSection
          selectedVideo={selectedVideo}
          showSubtitles={true}
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