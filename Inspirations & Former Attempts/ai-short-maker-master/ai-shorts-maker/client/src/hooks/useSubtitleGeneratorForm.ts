import { useState, useCallback } from "react"
import { useForm } from "react-hook-form"
import { useToast } from "./useToast"
import { useJobQueue } from "@/contexts/JobQueueContext"
import type { VideoItem } from "@/types/video"
import { defaultVideoConfig } from "@/types/video"

const defaultSubtitleStyle = {
  fontSize: 24,
  fontColor: "#FFFFFF",
  highlightColor: "#FF3B30",
  backgroundColor: "#000000",
  opacity: 80
}

export type SubtitleFormData = {
  originalLanguage: string
  subtitleWhisperModel: string
  burnSubtitles: boolean
  saveSrtSeparately: boolean
  translateSubtitles: boolean
  targetLanguage?: string
  translateTitle: boolean
  saveOriginalSrt: boolean
  saveTranslatedSrt: boolean
  subtitleStyle: {
    fontSize: number
    fontColor: string
    highlightColor: string
    backgroundColor: string
    opacity: number
  }
}

export function useSubtitleGeneratorForm(
  videoList: VideoItem[],
  setVideoList: (videos: VideoItem[]) => void,
  setSelectedVideo: (video: VideoItem | null) => void
) {
  const [loading, setLoading] = useState(false)
  const { toast } = useToast()
  const { addJob } = useJobQueue()

  const form = useForm<SubtitleFormData>({
    defaultValues: {
      originalLanguage: "auto",
      subtitleWhisperModel: "base",
      burnSubtitles: true,
      saveSrtSeparately: true,
      translateSubtitles: false,
      targetLanguage: "en",
      translateTitle: false,
      saveOriginalSrt: true,
      saveTranslatedSrt: true,
      subtitleStyle: defaultSubtitleStyle
    }
  })

  const onUpdateVideoConfig = useCallback((
    id: string,
    videos: VideoItem[],
    setVideos: (videos: VideoItem[]) => void
  ) => {
    const currentValues = form.getValues()

    setVideos(prev => prev.map(video => {
      if (video.id === id) {
        return {
          ...video,
          config: {
            ...video.config,
            originalLanguage: currentValues.originalLanguage,
            subtitleWhisperModel: currentValues.subtitleWhisperModel,
            burnSubtitles: currentValues.burnSubtitles,
            saveSrtSeparately: currentValues.saveSrtSeparately,
            translateSubtitles: currentValues.translateSubtitles,
            targetLanguage: currentValues.targetLanguage,
            translateTitle: currentValues.translateTitle,
            saveOriginalSrt: currentValues.saveOriginalSrt,
            saveTranslatedSrt: currentValues.saveTranslatedSrt,
            subtitleStyle: currentValues.subtitleStyle
          },
          lastModified: new Date().toISOString()
        }
      }
      return video
    }))
  }, [form])

  const loadVideoConfig = useCallback((video: VideoItem | null) => {
    if (!video || !video.config) {
      form.reset({
        originalLanguage: "auto",
        subtitleWhisperModel: "base",
        burnSubtitles: true,
        saveSrtSeparately: true,
        translateSubtitles: false,
        targetLanguage: "en",
        translateTitle: false,
        saveOriginalSrt: true,
        saveTranslatedSrt: true,
        subtitleStyle: defaultSubtitleStyle
      })
      return
    }

    form.reset({
      originalLanguage: video.config.originalLanguage || "auto",
      subtitleWhisperModel: video.config.subtitleWhisperModel || "base",
      burnSubtitles: video.config.burnSubtitles ?? true,
      saveSrtSeparately: video.config.saveSrtSeparately ?? true,
      translateSubtitles: video.config.translateSubtitles ?? false,
      targetLanguage: video.config.targetLanguage || "en",
      translateTitle: video.config.translateTitle ?? false,
      saveOriginalSrt: video.config.saveOriginalSrt ?? true,
      saveTranslatedSrt: video.config.saveTranslatedSrt ?? true,
      subtitleStyle: video.config.subtitleStyle || defaultSubtitleStyle
    })
  }, [form])

  const onUpdateAllVideos = useCallback((
    videos: VideoItem[],
    setVideos: (videos: VideoItem[]) => void
  ) => {
    const currentValues = form.getValues()

    setVideos(prev => prev.map(video => ({
      ...video,
      config: {
        ...video.config,
        originalLanguage: currentValues.originalLanguage,
        subtitleWhisperModel: currentValues.subtitleWhisperModel,
        burnSubtitles: currentValues.burnSubtitles,
        saveSrtSeparately: currentValues.saveSrtSeparately,
        translateSubtitles: currentValues.translateSubtitles,
        targetLanguage: currentValues.targetLanguage,
        translateTitle: currentValues.translateTitle,
        saveOriginalSrt: currentValues.saveOriginalSrt,
        saveTranslatedSrt: currentValues.saveTranslatedSrt,
        subtitleStyle: currentValues.subtitleStyle
      },
      lastModified: new Date().toISOString()
    })))
  }, [form])

  const onSubmit = async (data: SubtitleFormData) => {
    try {
      setLoading(true)
      if (videoList.length === 0) {
        throw new Error("Please add at least one video")
      }

      videoList.forEach(video => {
        addJob({
          name: video.title || video.name,
          type: 'subtitle',
          source: video.type,
          url: video.url,
          config: {
            originalLanguage: video.config.originalLanguage,
            subtitleWhisperModel: video.config.subtitleWhisperModel,
            burnSubtitles: video.config.burnSubtitles,
            saveSrtSeparately: video.config.saveSrtSeparately,
            translateSubtitles: video.config.translateSubtitles,
            targetLanguage: video.config.targetLanguage,
            translateTitle: video.config.translateTitle,
            saveOriginalSrt: video.config.saveOriginalSrt,
            saveTranslatedSrt: video.config.saveTranslatedSrt,
            subtitleStyle: video.config.subtitleStyle
          }
        })
      })

      toast({
        title: "Success",
        description: `Added ${videoList.length} videos to processing queue`,
      })

      setVideoList([])
      setSelectedVideo(null)
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

  return {
    form,
    loading,
    onSubmit,
    onUpdateVideoConfig,
    onUpdateAllVideos,
    loadVideoConfig
  }
}