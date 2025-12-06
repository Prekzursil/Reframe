import { createContext, useContext, useState, ReactNode } from "react"
import type { VideoItem } from "@/types/video"

interface VideoListContextType {
  shortsMakerVideos: VideoItem[]
  setShortsMakerVideos: (videos: VideoItem[]) => void
  shortsMakerSelectedVideo: VideoItem | null
  setShortsMakerSelectedVideo: (video: VideoItem | null) => void
  subtitleVideos: VideoItem[]
  setSubtitleVideos: (videos: VideoItem[]) => void
  subtitleSelectedVideo: VideoItem | null
  setSubtitleSelectedVideo: (video: VideoItem | null) => void
  translatorVideos: VideoItem[]
  setTranslatorVideos: (videos: VideoItem[]) => void
  translatorSelectedVideo: VideoItem | null
  setTranslatorSelectedVideo: (video: VideoItem | null) => void
  mergerVideos: VideoItem[]
  setMergerVideos: (videos: VideoItem[]) => void
  mergerSelectedVideo: VideoItem | null
  setMergerSelectedVideo: (video: VideoItem | null) => void
  mergerSubtitles: SubtitleFile[]
  setMergerSubtitles: (subtitles: SubtitleFile[]) => void
}

interface SubtitleFile {
  id: string
  name: string
  url: string
}

const VideoListContext = createContext<VideoListContextType | null>(null)

export function VideoListProvider({ children }: { children: ReactNode }) {
  const [shortsMakerVideos, setShortsMakerVideos] = useState<VideoItem[]>([])
  const [shortsMakerSelectedVideo, setShortsMakerSelectedVideo] = useState<VideoItem | null>(null)
  const [subtitleVideos, setSubtitleVideos] = useState<VideoItem[]>([])
  const [subtitleSelectedVideo, setSubtitleSelectedVideo] = useState<VideoItem | null>(null)
  const [translatorVideos, setTranslatorVideos] = useState<VideoItem[]>([])
  const [translatorSelectedVideo, setTranslatorSelectedVideo] = useState<VideoItem | null>(null)
  const [mergerVideos, setMergerVideos] = useState<VideoItem[]>([])
  const [mergerSelectedVideo, setMergerSelectedVideo] = useState<VideoItem | null>(null)
  const [mergerSubtitles, setMergerSubtitles] = useState<SubtitleFile[]>([])

  return (
    <VideoListContext.Provider value={{
      shortsMakerVideos,
      setShortsMakerVideos,
      shortsMakerSelectedVideo,
      setShortsMakerSelectedVideo,
      subtitleVideos,
      setSubtitleVideos,
      subtitleSelectedVideo,
      setSubtitleSelectedVideo,
      translatorVideos,
      setTranslatorVideos,
      translatorSelectedVideo,
      setTranslatorSelectedVideo,
      mergerVideos,
      setMergerVideos,
      mergerSelectedVideo,
      setMergerSelectedVideo,
      mergerSubtitles,
      setMergerSubtitles
    }}>
      {children}
    </VideoListContext.Provider>
  )
}

export function useVideoList() {
  const context = useContext(VideoListContext)
  if (!context) {
    throw new Error("useVideoList must be used within a VideoListProvider")
  }
  return context
}