import { useState, useCallback, useEffect } from "react"
import { useForm } from "react-hook-form"
import { useToast } from "./useToast"
import { useJobQueue } from "@/contexts/JobQueueContext"
import { useLanguage } from "@/contexts/LanguageContext"
import type { VideoItem } from "@/types/video"

export type SubtitleTranslatorFormData = {
  targetLanguage: string
}

export function useSubtitleTranslatorForm(
  videoList: VideoItem[],
  setVideoList: (videos: VideoItem[]) => void,
  setSelectedVideo: (video: VideoItem | null) => void
) {
  const [loading, setLoading] = useState(false)
  const [useMasterLanguage, setUseMasterLanguage] = useState(false)
  const [masterLanguage, setMasterLanguage] = useState("en")
  const { toast } = useToast()
  const { addJob } = useJobQueue()
  const { language } = useLanguage()

  const form = useForm<SubtitleTranslatorFormData>({
    defaultValues: {
      targetLanguage: language
    }
  })

  const onSubmit = async (data: SubtitleTranslatorFormData) => {
    try {
      setLoading(true)
      if (videoList.length === 0) {
        throw new Error("Please add at least one subtitle file")
      }

      videoList.forEach(video => {
        addJob({
          name: video.title || video.name,
          type: 'translation',
          source: video.type,
          url: video.url,
          config: {
            targetLanguage: useMasterLanguage ? masterLanguage : (video.config.targetLanguage || language)
          }
        })
      })

      toast({
        title: "Success",
        description: `Added ${videoList.length} files to processing queue`,
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

  const handleLanguageChange = (id: string, value: string) => {
    setVideoList(prev => prev.map(video => {
      if (video.id === id) {
        return {
          ...video,
          config: {
            ...video.config,
            targetLanguage: value
          },
          lastModified: new Date().toISOString()
        }
      }
      return video
    }))
  }

  return {
    form,
    loading,
    onSubmit,
    handleLanguageChange,
    useMasterLanguage,
    setUseMasterLanguage,
    masterLanguage,
    setMasterLanguage
  }
}