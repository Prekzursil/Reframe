import { useState } from "react"
import { Label } from "@/components/ui/label"
import { VideoUploadZone } from "@/components/VideoUploadZone"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import type { VideoItem } from "@/types/video"
import { VideoList } from "@/components/VideoList"
import type { VideoConfig } from "@/types/video"
import { defaultVideoConfig } from "@/types/video"
import { fetchVideoMetadata } from "@/api/shorts"
import { useToast } from "@/hooks/useToast"

interface VideoInputSectionProps {
  videoList: VideoItem[]
  onVideosChange: (videos: VideoItem[]) => void
  onVideoSelect: (video: VideoItem | null) => void
  selectedVideo: VideoItem | null
  onVideoConfigUpdate: (id: string, config: VideoConfig) => void
  globalConfig?: VideoConfig
  isProcessing?: boolean
}

export function VideoInputSection({
  videoList,
  onVideosChange,
  onVideoSelect,
  selectedVideo,
  onVideoConfigUpdate,
  globalConfig,
  isProcessing
}: VideoInputSectionProps) {
  const [urlInput, setUrlInput] = useState("")
  const [loading, setLoading] = useState(false)
  const { toast } = useToast()

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files) {
      const newVideos = Array.from(files).map((file) => ({
        id: Math.random().toString(36).substr(2, 9),
        name: file.name,
        url: URL.createObjectURL(file),
        type: "local" as const,
        config: { ...defaultVideoConfig }
      }))
      const updatedList = [...videoList, ...newVideos]
      onVideosChange(updatedList)
      if (!selectedVideo && newVideos.length > 0) {
        onVideoSelect(newVideos[0])
      }
    }
    event.target.value = ""
  }

  const isValidVideoUrl = (url: string) => {
    try {
      const urlObj = new URL(url);
      // Support common video platforms
      const validDomains = [
        'youtube.com', 'youtu.be',
        'vimeo.com',
        'dailymotion.com',
        'facebook.com',
        'twitter.com', 'x.com',
        'instagram.com',
        'tiktok.com'
      ];
      return validDomains.some(domain => urlObj.hostname.includes(domain));
    } catch {
      return false;
    }
  }

  const handleUrlAdd = async () => {
    const urls = urlInput
      .split("\n")
      .map(url => url.trim())
      .filter(url => url && isValidVideoUrl(url));

    if (urls.length > 0) {
      setLoading(true)
      try {
        const newVideos = await Promise.all(urls.map(async (url) => {
          try {
            const metadata = await fetchVideoMetadata(url)
            return {
              id: Math.random().toString(36).substr(2, 9),
              name: url,
              url: url,
              type: "url" as const,
              title: `${metadata.title} - ${url} - (${metadata.platform})`,
              thumbnail: metadata.thumbnail,
              config: { ...defaultVideoConfig }
            }
          } catch (error) {
            toast({
              variant: "destructive",
              title: "Error",
              description: `Failed to fetch metadata for ${url}`
            })
            return null
          }
        }))

        const validVideos = newVideos.filter(video => video !== null) as VideoItem[]
        const updatedList = [...videoList, ...validVideos]
        onVideosChange(updatedList)
        if (!selectedVideo && validVideos.length > 0) {
          onVideoSelect(validVideos[0])
        }

        setUrlInput("")
      } catch (error) {
        toast({
          variant: "destructive",
          title: "Error",
          description: "Failed to process video URLs"
        })
      } finally {
        setLoading(false)
      }
    }
  }

  const handleVideoRemove = (id: string) => {
    onVideosChange(videoList.filter(video => video.id !== id))
    if (selectedVideo?.id === id) {
      onVideoSelect(null)
    }
  }

  const handleVideoSelect = (video: VideoItem) => {
    if (selectedVideo?.id === video.id) {
      onVideoSelect(null)
    } else {
      onVideoSelect(video)
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>Add Videos</Label>
        <div className="grid gap-4">
          <VideoUploadZone
            onFileChange={handleFileChange}
            id="video-upload"
            label="Drop video files here or click to browse"
          />

          <div className="space-y-2">
            <Label>Or add video URLs</Label>
            <div className="flex gap-2">
              <Textarea
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="Enter video URLs (one per line)&#10;Supported: YouTube, Vimeo, DailyMotion, Facebook, Twitter, Instagram, TikTok"
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

      {videoList.length > 0 && (
        <div className="space-y-2">
          <Label>Videos to Process</Label>
          <VideoList
            videos={videoList}
            onVideosReorder={onVideosChange}
            onVideoRemove={handleVideoRemove}
            onVideoSelect={handleVideoSelect}
            isProcessing={isProcessing}
          />
        </div>
      )}
    </div>
  )
}