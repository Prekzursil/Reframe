export interface FormData {
  prompt: string
  minDuration: string
  maxDuration: string
  initialWhisperModel: string
  generateSubtitles: boolean
  originalLanguage: string
  burnSubtitles: boolean
  saveSrtSeparately: boolean
  translateSubtitles: boolean
  targetLanguage?: string
  translateTitle: boolean
  saveOriginalSrt: boolean
  saveTranslatedSrt: boolean
  subtitleWhisperModel: string
  subtitleStyle: {
    fontSize: number
    fontColor: string
    highlightColor: string
    backgroundColor: string
    opacity: number
  }
  outputFolder: string
}

export const defaultFormValues: FormData = {
  minDuration: "30",
  maxDuration: "60",
  initialWhisperModel: "base",
  generateSubtitles: true,
  originalLanguage: "auto",
  burnSubtitles: true,
  saveSrtSeparately: true,
  translateSubtitles: false,
  targetLanguage: "en",
  translateTitle: false,
  saveOriginalSrt: true,
  saveTranslatedSrt: true,
  subtitleWhisperModel: "base",
  subtitleStyle: {
    fontSize: 24,
    fontColor: "#FFFFFF",
    highlightColor: "#FF3B30",
    backgroundColor: "#000000",
    opacity: 80
  },
  outputFolder: "",
  prompt: ""
}