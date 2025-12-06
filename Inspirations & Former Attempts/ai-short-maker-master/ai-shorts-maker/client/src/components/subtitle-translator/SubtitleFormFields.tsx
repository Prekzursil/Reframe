import { Control } from "react-hook-form"
import { Label } from "@/components/ui/label"
import { SubtitleInputSection } from "./SubtitleInputSection"
import type { VideoItem } from "@/types/video"
import type { SubtitleTranslatorFormData } from "@/hooks/useSubtitleTranslatorForm"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { LANGUAGES } from "@/lib/constants"
import { FileVideo, Languages, X } from "lucide-react"
import { Button } from "@/components/ui/button"

interface SubtitleFormFieldsProps {
  videoList: VideoItem[]
  setVideoList: (videos: VideoItem[]) => void
  selectedVideo: VideoItem | null
  setSelectedVideo: (video: VideoItem | null) => void
  loading: boolean
  control: Control<SubtitleTranslatorFormData>
  onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void
  onUrlAdd: (urls: string[]) => void
  onVideoRemove: (id: string) => void
  onVideoSelect: (video: VideoItem) => void
  onLanguageChange: (id: string, value: string) => void
  useMasterLanguage: boolean
  masterLanguage: string
}

export function SubtitleFormFields({
  videoList,
  setVideoList,
  selectedVideo,
  setSelectedVideo,
  loading,
  control,
  onFileChange,
  onUrlAdd,
  onVideoRemove,
  onVideoSelect,
  onLanguageChange,
  useMasterLanguage,
  masterLanguage
}: SubtitleFormFieldsProps) {
  return (
    <div className="space-y-6">
      <SubtitleInputSection
        onUrlAdd={onUrlAdd}
        onFileChange={onFileChange}
        loading={loading}
      />

      {videoList.length > 0 && (
        <div className="space-y-2">
          <Label>Subtitles to Process</Label>
          <div className="space-y-2">
            {videoList.map((video) => (
              <div
                key={video.id}
                className="flex items-center gap-2 p-2 rounded-lg border bg-card/50 hover:bg-card/80 transition-colors"
              >
                <FileVideo className="h-4 w-4 text-primary shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{video.name}</p>
                  {!useMasterLanguage && (
                    <div className="flex items-center gap-1 mt-1">
                      <Languages className="h-3 w-3 text-muted-foreground" />
                      <Select
                        value={video.config?.targetLanguage || "en"}
                        onValueChange={(value) => onLanguageChange(video.id, value)}
                        disabled={loading}
                      >
                        <SelectTrigger className="h-7">
                          <SelectValue placeholder="Target language" />
                        </SelectTrigger>
                        <SelectContent>
                          {LANGUAGES.map((lang) => (
                            <SelectItem key={lang.value} value={lang.value}>
                              {lang.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onVideoRemove(video.id)}
                  className="shrink-0"
                  disabled={loading}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ))}
          </div>
          <p className="text-sm text-muted-foreground">
            {videoList.length} file{videoList.length !== 1 ? 's' : ''} selected
            {useMasterLanguage && ` (all translating to ${LANGUAGES.find(l => l.value === masterLanguage)?.label})`}
          </p>
        </div>
      )}
    </div>
  )
}