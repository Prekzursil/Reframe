import { useState, useEffect } from "react"
import type { VideoItem } from "@/types/video"
import { useSubtitleGeneratorForm } from "@/hooks/useSubtitleGeneratorForm"
import { SubtitleFormFields } from "./SubtitleFormFields"
import { SubtitleFormActions } from "./SubtitleFormActions"
import { defaultVideoConfig } from "@/types/video"
import { useToast } from "@/hooks/useToast"

interface SubtitleGeneratorFormProps {
  videoList: VideoItem[]
  setVideoList: (videos: VideoItem[]) => void
  selectedVideo: VideoItem | null
  setSelectedVideo: (video: VideoItem | null) => void
  isStyleOpen: boolean
  setIsStyleOpen: (open: boolean) => void
}

export function SubtitleGeneratorForm({
  videoList,
  setVideoList,
  selectedVideo,
  setSelectedVideo,
  isStyleOpen,
  setIsStyleOpen
}: SubtitleGeneratorFormProps) {
  const {
    form,
    loading,
    onSubmit,
    onUpdateVideoConfig,
    onUpdateAllVideos,
    loadVideoConfig
  } = useSubtitleGeneratorForm(
    videoList,
    setVideoList,
    setSelectedVideo
  )

  const { toast } = useToast()
  const watchSubtitles = true
  const watchTranslate = form.watch("translateSubtitles", false)

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

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files) {
      const newVideos = Array.from(files).map((file) => ({
        id: Math.random().toString(36).substr(2, 9),
        name: file.name,
        url: URL.createObjectURL(file),
        type: "local" as const,
        config: { ...defaultVideoConfig },
        lastModified: new Date().toISOString()
      }))
      setVideoList((prev) => [...prev, ...newVideos])
      if (!selectedVideo && newVideos.length > 0) {
        setSelectedVideo(newVideos[0])
      }
    }
    event.target.value = ""
  }

  const handleUrlAdd = (urls: string[]) => {
    if (urls.length === 0) {
      toast({
        variant: "destructive",
        title: "Error",
        description: "Please enter at least one valid URL"
      })
      return
    }

    const newVideos = urls.map(url => ({
      id: Math.random().toString(36).substr(2, 9),
      name: url,
      url: url.trim(),
      type: "url" as const,
      title: `Loading title for ${url}...`,
      config: { ...defaultVideoConfig },
      lastModified: new Date().toISOString()
    }))
    setVideoList((prev) => [...prev, ...newVideos])
    if (!selectedVideo && newVideos.length > 0) {
      setSelectedVideo(newVideos[0])
    }

    newVideos.forEach((video, index) => {
      setTimeout(() => {
        setVideoList(prev => {
          const updatedList = [...prev]
          const videoIndex = updatedList.findIndex(v => v.id === video.id)
          if (videoIndex !== -1) {
            updatedList[videoIndex] = {
              ...updatedList[videoIndex],
              title: `Video ${index + 1} from ${new URL(video.url).hostname}`
            }
          }
          return updatedList
        })
      }, 1000 + (index * 500))
    })
  }

  const handleVideoRemove = (id: string) => {
    setVideoList((prev) => prev.filter(video => video.id !== id))
    if (selectedVideo?.id === id) {
      setSelectedVideo(null)
    }
  }

  const handleVideoSelect = (video: VideoItem) => {
    if (selectedVideo?.id === video.id) {
      setSelectedVideo(null)
    } else {
      setSelectedVideo(video)
    }
  }

  const handleSaveVideoSettings = () => {
    if (selectedVideo) {
      onUpdateVideoConfig(selectedVideo.id, videoList, setVideoList)
      toast({
        title: "Success",
        description: "Video settings saved successfully"
      })
    }
  }

  const handleApplyToAll = () => {
    onUpdateAllVideos(videoList, setVideoList)
    toast({
      title: "Success",
      description: "Settings applied to all videos"
    })
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
      <SubtitleFormFields
        videoList={videoList}
        setVideoList={setVideoList}
        selectedVideo={selectedVideo}
        setSelectedVideo={setSelectedVideo}
        isStyleOpen={isStyleOpen}
        setIsStyleOpen={setIsStyleOpen}
        loading={loading}
        control={form.control}
        watchSubtitles={watchSubtitles}
        watchTranslate={watchTranslate}
        onFileChange={handleFileChange}
        onUrlAdd={handleUrlAdd}
        onVideoRemove={handleVideoRemove}
        onVideoSelect={handleVideoSelect}
      />
      <SubtitleFormActions
        loading={loading}
        selectedVideo={selectedVideo}
        onSaveVideoSettings={handleSaveVideoSettings}
        onApplyToAll={handleApplyToAll}
        videoListLength={videoList.length}
      />
    </form>
  )
}