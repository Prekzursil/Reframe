import { useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { cn } from "@/lib/utils"
import { Button } from "./ui/button"
import {
  GripVertical,
  FileVideo,
  Link as LinkIcon,
  X,
  Plus,
  Settings,
  Clock
} from "lucide-react"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./ui/tooltip"
import { Badge } from "./ui/badge"
import type { VideoItem } from "@/types/video"
import { format, formatDistanceToNow } from 'date-fns'

interface VideoItemProps {
  video: VideoItem
  onRemove: (id: string) => void
  onSelect: (video: VideoItem) => void
  onAddToQueue: (video: VideoItem) => void
  isProcessing?: boolean
}

export function VideoItem({
  video,
  onRemove,
  onSelect,
  onAddToQueue,
  isProcessing
}: VideoItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: video.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  const getLastModifiedText = () => {
    if (!video.lastModified) return ""
    const date = new Date(video.lastModified)
    const distance = formatDistanceToNow(date, { addSuffix: true })
    const fullDate = format(date, 'MMM d, yyyy h:mm a')
    return `Last modified ${distance} (${fullDate})`
  }

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    onSelect(video)
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      onClick={handleClick}
      className={cn(
        "flex items-center gap-2 p-3 bg-card/50 backdrop-blur-sm rounded-lg border shadow-sm",
        "transition-all duration-200 hover:shadow-md hover:scale-[1.01] cursor-pointer group",
        "hover:border-primary/50",
        isDragging && "opacity-50",
        isProcessing && "opacity-70 pointer-events-none",
        video.selected && "ring-2 ring-primary border-primary bg-primary/5"
      )}
    >
      {!isProcessing && (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  onRemove(video.id)
                }}
                className="text-muted-foreground hover:text-destructive transition-colors shrink-0"
              >
                <X className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>Remove Video</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                onAddToQueue(video)
              }}
              className="text-muted-foreground hover:text-primary transition-colors shrink-0"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>Add to Queue</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              {...attributes}
              {...listeners}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
              }}
              className="cursor-grab active:cursor-grabbing hover:text-primary transition-colors shrink-0"
            >
              <GripVertical className="h-5 w-5" />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            <p>Drag to reorder</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      {video.type === "local" ? (
        <FileVideo className="h-5 w-5 text-primary shrink-0" />
      ) : (
        <LinkIcon className="h-5 w-5 text-primary shrink-0" />
      )}

      <div className="min-w-0 flex-1">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium w-full">
                  {video.title || video.name}
                </span>
                <div className="flex items-center gap-2 shrink-0">
                  {video.loading && (
                    <Badge variant="secondary" className="animate-pulse">
                      Loading...
                    </Badge>
                  )}
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <p>{video.title || video.name}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
        {video.lastModified && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
            <Clock className="h-3 w-3" />
            <span className="truncate">{getLastModifiedText()}</span>
          </div>
        )}
      </div>

      <Button
        variant="ghost"
        size="icon"
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          onSelect(video)
        }}
        className="text-muted-foreground hover:text-primary transition-colors shrink-0"
      >
        <Settings className="h-4 w-4" />
      </Button>
    </div>
  )
}