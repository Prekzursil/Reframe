import ReactPlayer from "react-player"
import { useState } from "react"
import { LoadingSpinner } from "./LoadingSpinner"
import { cn } from "@/lib/utils"

interface VideoPreviewProps {
  url: string
  showSubtitles: boolean
  subtitleStyle?: {
    fontSize: number
    fontColor: string
    highlightColor: string
    backgroundColor: string
    opacity: number
  }
  className?: string
}

export function VideoPreview({ url, showSubtitles, subtitleStyle, className }: VideoPreviewProps) {
  const [isLoading, setIsLoading] = useState(true)

  return (
    <div className={cn(
      "relative rounded-lg overflow-hidden bg-black/5",
      "transition-all duration-200 transform hover:scale-[1.01]",
      className
    )}>
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80 backdrop-blur-sm">
          <LoadingSpinner />
        </div>
      )}
      <div className="aspect-[9/16] relative">
        <ReactPlayer
          url={url}
          width="100%"
          height="100%"
          playing={false}
          controls
          onReady={() => setIsLoading(false)}
        />
        {showSubtitles && (
          <div
            className="absolute bottom-0 left-0 right-0 p-4 text-center"
            style={{
              fontSize: `${subtitleStyle?.fontSize || 24}px`,
              color: subtitleStyle?.fontColor || "#FFFFFF",
              backgroundColor: `${subtitleStyle?.backgroundColor}${Math.round((subtitleStyle?.opacity || 80) * 2.55).toString(16).padStart(2, '0')}`,
              textShadow: '2px 2px 4px rgba(0,0,0,0.5)'
            }}
          >
            <span
              style={{
                backgroundColor: subtitleStyle?.highlightColor || "#FF3B30",
                padding: "0.2em 0.4em",
                borderRadius: "0.2em",
                boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
              }}
            >
              Sample subtitle text
            </span>
          </div>
        )}
      </div>
    </div>
  )
}