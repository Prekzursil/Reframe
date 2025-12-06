import { useVideoForm } from "@/hooks/useVideoForm"
import type { VideoItem } from "@/types/video"
import { VideoInputSection } from "./VideoInputSection"
import { OutputFolderSection } from "./OutputFolderSection"
import { PromptSection } from "./PromptSection"
import { SubtitleGenerationSettings } from "@/components/SubtitleGenerationSettings"
import { Button } from "@/components/ui/button"
import { Loader2, Download } from "lucide-react"
import { useEffect } from "react"

interface FormSectionProps {
  videoList: VideoItem[]
  setVideoList: (videos: VideoItem[]) => void
  selectedVideo: VideoItem | null
  setSelectedVideo: (video: VideoItem | null) => void
  isStyleOpen: boolean
  setIsStyleOpen: (open: boolean) => void
}

export function FormSection({
  videoList,
  setVideoList,
  selectedVideo,
  setSelectedVideo,
  isStyleOpen,
  setIsStyleOpen
}: FormSectionProps) {
  const {
    form,
    isLoading,
    onUpdateVideoConfig,
    onUpdateAllVideos,
    onSubmit,
    loadVideoConfig
  } = useVideoForm()

  const { watch, setValue, control } = form
  const watchSubtitles = watch("generateSubtitles", true)
  const watchTranslate = watch("translateSubtitles", false)

  // Watch form changes and update video config
  useEffect(() => {
    const subscription = form.watch(() => {
      if (selectedVideo) {
        onUpdateVideoConfig(selectedVideo.id, videoList, setVideoList)
      }
    })
    return () => subscription.unsubscribe()
  }, [selectedVideo, videoList, setVideoList, form, onUpdateVideoConfig])

  // Load video config when selection changes
  useEffect(() => {
    loadVideoConfig(selectedVideo)
  }, [selectedVideo, loadVideoConfig])

  const handleSubmit = form.handleSubmit((data) => {
    onSubmit(data, videoList, () => {
      setVideoList([])
      setSelectedVideo(null)
    })
  })

  const handleApplyToAll = () => {
    onUpdateAllVideos(videoList, setVideoList)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <OutputFolderSection
        value={watch("outputFolder")}
        onChange={(value) => setValue("outputFolder", value)}
      />

      <VideoInputSection
        videoList={videoList}
        onVideosChange={setVideoList}
        onVideoSelect={setSelectedVideo}
        selectedVideo={selectedVideo}
        onVideoConfigUpdate={(id) => onUpdateVideoConfig(id, videoList, setVideoList)}
        isProcessing={isLoading}
      />

      <PromptSection
        prompt={watch("prompt")}
        onPromptChange={(value) => setValue("prompt", value)}
        whisperModel={watch("initialWhisperModel")}
        onWhisperModelChange={(value) => setValue("initialWhisperModel", value)}
        durationMin={watch("minDuration")}
        onDurationMinChange={(value) => setValue("minDuration", value)}
        durationMax={watch("maxDuration")}
        onDurationMaxChange={(value) => setValue("maxDuration", value)}
        disabled={!selectedVideo}
      />

      <SubtitleGenerationSettings
        control={control}
        watchSubtitles={watchSubtitles}
        watchTranslate={watchTranslate}
        isStyleOpen={isStyleOpen}
        onStyleOpenChange={setIsStyleOpen}
        disabled={!selectedVideo}
      />

      <div className="flex gap-2">
        <Button
          type="button"
          variant="secondary"
          className="flex-1"
          onClick={handleApplyToAll}
          disabled={videoList.length === 0 || isLoading}
        >
          <Download className="h-4 w-4 mr-2" />
          Apply Settings to All Videos
        </Button>
        <Button
          type="submit"
          className="flex-1 bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 transition-all duration-200 transform hover:scale-[1.02]"
          disabled={isLoading || videoList.length === 0}
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
    </form>
  )
}