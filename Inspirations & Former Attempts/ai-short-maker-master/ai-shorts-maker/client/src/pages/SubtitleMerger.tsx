import { useState } from "react"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription
} from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Loader2, Combine, Settings2 } from "lucide-react"
import { useToast } from "@/hooks/useToast"
import { useJobQueue } from "@/contexts/JobQueueContext"
import { VideoUploadZone } from "@/components/VideoUploadZone"
import { Input } from "@/components/ui/input"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { FileVideo, FileCode, AlertCircle } from "lucide-react"
import { VideoItem } from "@/types/video"
import { useVideoList } from "@/contexts/VideoListContext"

interface SubtitleFile {
  id: string
  name: string
  url: string
}

export function SubtitleMerger() {
  const [loading, setLoading] = useState(false)
  const [outputFolder, setOutputFolder] = useState("")
  const { toast } = useToast()
  const { addJob } = useJobQueue()
  const {
    mergerVideos: videos,
    setMergerVideos: setVideos,
    mergerSubtitles: subtitles,
    setMergerSubtitles: setSubtitles
  } = useVideoList()

  const handleVideoUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files) {
      const newVideos = Array.from(files).map((file) => ({
        id: Math.random().toString(36).substr(2, 9),
        name: file.name,
        url: URL.createObjectURL(file),
        type: "local" as const,
        title: file.name,
        lastModified: new Date().toISOString()
      }))
      setVideos((prev) => [...prev, ...newVideos])
    }
    event.target.value = ""
  }

  const handleSubtitleUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files) {
      const newSubtitles = Array.from(files).map((file) => ({
        id: Math.random().toString(36).substr(2, 9),
        name: file.name,
        url: URL.createObjectURL(file)
      }))
      setSubtitles((prev) => [...prev, ...newSubtitles])
    }
    event.target.value = ""
  }

  const handleVideoRemove = (id: string) => {
    setVideos((prev) => prev.filter((video) => video.id !== id))
  }

  const handleSubtitleRemove = (id: string) => {
    setSubtitles((prev) => prev.filter((subtitle) => subtitle.id !== id))
  }

  const handleSubmit = async () => {
    try {
      setLoading(true)

      if (videos.length === 0 || subtitles.length === 0) {
        throw new Error("Please upload both video and subtitle files")
      }

      if (videos.length !== subtitles.length) {
        throw new Error("Number of videos and subtitle files must match")
      }

      videos.forEach((video, index) => {
        addJob({
          name: `${video.name} + ${subtitles[index].name}`,
          type: 'merge',
          source: 'local',
          url: video.url,
          config: {
            subtitleUrl: subtitles[index].url,
            outputFolder: outputFolder || undefined
          }
        })
      })

      toast({
        title: "Success",
        description: `Added ${videos.length} merge jobs to processing queue`,
      })

      // Clear the form
      setVideos([])
      setSubtitles([])
    } catch (error) {
      toast({
        variant: "destructive",
        title: "Error",
        description: error.message,
      })
    } finally {
      setLoading(false)
    }
  }

  const handleBrowseFolder = async () => {
    try {
      // @ts-ignore - window.showDirectoryPicker is not in TypeScript types yet
      const directoryHandle = await window.showDirectoryPicker()
      setOutputFolder(directoryHandle.name)
    } catch (error) {
      // Only log if it's not an abort error
      if (!(error instanceof Error) || !error.message.includes('abort')) {
        console.error("Error selecting directory:", error)
      }
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 mb-20">
      <Card className="backdrop-blur-sm bg-background/95">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Combine className="h-6 w-6" />
            Subtitle Merger
          </CardTitle>
          <CardDescription>
            Merge subtitle files with videos
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Upload Videos</Label>
              <VideoUploadZone
                onFileChange={handleVideoUpload}
                id="video-upload"
                label="Drop video files here or click to browse"
              />
              {videos.length > 0 && (
                <div className="space-y-2 mt-2">
                  {videos.map((video) => (
                    <div
                      key={video.id}
                      className="flex items-center gap-2 p-2 rounded-lg border bg-card/50"
                    >
                      <FileVideo className="h-4 w-4 text-primary" />
                      <span className="flex-1 truncate text-sm">{video.name}</span>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleVideoRemove(video.id)}
                      >
                        <span className="sr-only">Remove</span>
                        <AlertCircle className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label>Upload Subtitle Files (SRT)</Label>
              <VideoUploadZone
                onFileChange={handleSubtitleUpload}
                accept=".srt"
                id="subtitle-upload"
                label="Drop SRT files here or click to browse"
              />
              {subtitles.length > 0 && (
                <div className="space-y-2 mt-2">
                  {subtitles.map((subtitle) => (
                    <div
                      key={subtitle.id}
                      className="flex items-center gap-2 p-2 rounded-lg border bg-card/50"
                    >
                      <FileCode className="h-4 w-4 text-primary" />
                      <span className="flex-1 truncate text-sm">
                        {subtitle.name}
                      </span>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleSubtitleRemove(subtitle.id)}
                      >
                        <span className="sr-only">Remove</span>
                        <AlertCircle className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {(videos.length > 0 || subtitles.length > 0) && (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  {videos.length === subtitles.length
                    ? "Files will be matched in order. Drag to reorder if needed."
                    : "Number of videos and subtitle files must match."}
                </AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              <Label>Output Folder (Optional)</Label>
              <div className="flex gap-2">
                <Input
                  value={outputFolder}
                  onChange={(e) => setOutputFolder(e.target.value)}
                  placeholder="Select output folder..."
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={handleBrowseFolder}
                  className="shrink-0"
                >
                  Browse
                </Button>
              </div>
            </div>
          </div>

          <Button
            onClick={handleSubmit}
            disabled={loading || videos.length === 0 || subtitles.length === 0}
            className="w-full bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700"
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Adding to Queue...
              </>
            ) : (
              <>
                <Settings2 className="mr-2 h-4 w-4" />
                Merge Subtitles
              </>
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}