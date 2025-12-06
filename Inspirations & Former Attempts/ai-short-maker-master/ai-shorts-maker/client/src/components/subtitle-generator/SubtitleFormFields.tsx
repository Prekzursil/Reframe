import { Control } from "react-hook-form"
import { Label } from "@/components/ui/label"
import { VideoList } from "@/components/VideoList"
import { SubtitleGenerationSettings } from "@/components/SubtitleGenerationSettings"
import { UrlInputSection } from "./UrlInputSection"
import type { VideoItem } from "@/types/video"
import type { SubtitleFormData } from "@/hooks/useSubtitleGeneratorForm"

interface SubtitleFormFieldsProps {
  videoList: VideoItem[]
  setVideoList: (videos: VideoItem[]) => void
  selectedVideo: VideoItem | null
  setSelectedVideo: (video: VideoItem | null) => void
  isStyleOpen: boolean
  setIsStyleOpen: (open: boolean) => void
  loading: boolean
  control: Control<SubtitleFormData>
  watchSubtitles: boolean
  watchTranslate: boolean
  onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void
  onUrlAdd: (urls: string[]) => void
  onVideoRemove: (id: string) => void
  onVideoSelect: (video: VideoItem) => void
}

export function SubtitleFormFields({
  videoList,
  setVideoList,
  selectedVideo,
  setSelectedVideo,
  isStyleOpen,
  setIsStyleOpen,
  loading,
  control,
  watchSubtitles,
  watchTranslate,
  onFileChange,
  onUrlAdd,
  onVideoRemove,
  onVideoSelect
}: SubtitleFormFieldsProps) {
  return (
    <div className="space-y-6">
      <UrlInputSection
        onUrlAdd={onUrlAdd}
        onFileChange={onFileChange}
        loading={loading}
      />

      {videoList.length > 0 && (
        <div className="space-y-2">
          <Label>Videos to Process</Label>
          <VideoList
            videos={videoList}
            onVideosReorder={setVideoList}
            onVideoRemove={onVideoRemove}
            onVideoSelect={onVideoSelect}
            isProcessing={loading}
            jobType="subtitle"
          />
        </div>
      )}

      <div className={`space-y-6 transition-opacity duration-200 ${!selectedVideo ? 'opacity-50 pointer-events-none' : ''}`}>
        <div className="p-4 rounded-lg border bg-background/95 backdrop-blur-sm">
          <SubtitleGenerationSettings
            control={control}
            watchSubtitles={watchSubtitles}
            watchTranslate={watchTranslate}
            isStyleOpen={isStyleOpen}
            onStyleOpenChange={setIsStyleOpen}
            disabled={!selectedVideo}
          />
        </div>
      </div>
    </div>
  )
}