import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Languages } from "lucide-react"
import { useVideoList } from "@/contexts/VideoListContext"
import { SubtitleFormFields } from "@/components/subtitle-translator/SubtitleFormFields"
import { SubtitleFormActions } from "@/components/subtitle-translator/SubtitleFormActions"
import { useSubtitleTranslatorForm } from "@/hooks/useSubtitleTranslatorForm"
import { useToast } from "@/hooks/useToast"
import { defaultVideoConfig } from "@/types/video"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { LANGUAGES } from "@/lib/constants"
import type { VideoItem } from "@/types/video"
import { Button } from "@/components/ui/button"
import { Loader2 } from "lucide-react"

export function SubtitleTranslator() {
  const {
    translatorVideos: videoList,
    setTranslatorVideos: setVideoList,
    translatorSelectedVideo: selectedVideo,
    setTranslatorSelectedVideo: setSelectedVideo
  } = useVideoList()

  const { toast } = useToast()
  const {
    form,
    loading,
    onSubmit,
    handleLanguageChange,
    useMasterLanguage,
    setUseMasterLanguage,
    masterLanguage,
    setMasterLanguage
  } = useSubtitleTranslatorForm(videoList, setVideoList, setSelectedVideo)

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
      config: { ...defaultVideoConfig },
      lastModified: new Date().toISOString()
    }))
    setVideoList((prev) => [...prev, ...newVideos])
    if (!selectedVideo && newVideos.length > 0) {
      setSelectedVideo(newVideos[0])
    }
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

  return (
    <Card className="backdrop-blur-sm bg-background/95">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Languages className="h-6 w-6" />
          Subtitle Translator
        </CardTitle>
        <CardDescription>
          Translate subtitle files to different languages
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
          <div className="space-y-4">
            <div className="flex items-center space-x-2">
              <Switch
                checked={useMasterLanguage}
                onCheckedChange={setUseMasterLanguage}
                disabled={loading}
              />
              <Label>Use Master Language</Label>
            </div>

            {useMasterLanguage && (
              <div className="space-y-2">
                <Label>Master Target Language</Label>
                <Select
                  value={masterLanguage}
                  onValueChange={setMasterLanguage}
                  disabled={loading}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select target language" />
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

          <SubtitleFormFields
            videoList={videoList}
            setVideoList={setVideoList}
            selectedVideo={selectedVideo}
            setSelectedVideo={setSelectedVideo}
            loading={loading}
            control={form.control}
            onFileChange={handleFileChange}
            onUrlAdd={handleUrlAdd}
            onVideoRemove={handleVideoRemove}
            onVideoSelect={handleVideoSelect}
            onLanguageChange={handleLanguageChange}
            useMasterLanguage={useMasterLanguage}
            masterLanguage={masterLanguage}
          />

          <Button
            type="submit"
            className="w-full bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700"
            disabled={loading || videoList.length === 0}
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Adding to Queue...
              </>
            ) : (
              "Add to Queue"
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}