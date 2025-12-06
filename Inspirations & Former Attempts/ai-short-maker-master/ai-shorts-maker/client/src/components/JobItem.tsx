import { useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { cn } from "@/lib/utils"
import { Button } from "./ui/button"
import {
  GripVertical,
  FileVideo,
  Link as LinkIcon,
  X,
  ChevronsUp,
  ChevronsDown,
  Settings
} from "lucide-react"
import { useJobQueue, Job } from "@/contexts/JobQueueContext"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./ui/tooltip"
import { Badge } from "./ui/badge"
import { LANGUAGES } from "@/lib/constants"

const jobTypeIcons = {
  shorts: FileVideo,
  subtitle: FileVideo,
  translation: FileVideo,
  merge: FileVideo
}

const jobTypeLabels = {
  shorts: "Shorts Maker",
  subtitle: "Subtitle Generator",
  translation: "Subtitle Translator",
  merge: "Subtitle Merger"
}

const jobTypeColors = {
  shorts: "bg-blue-500/10 text-blue-500 hover:bg-blue-500/20",
  subtitle: "bg-green-500/10 text-green-500 hover:bg-green-500/20",
  translation: "bg-purple-500/10 text-purple-500 hover:bg-purple-500/20",
  merge: "bg-orange-500/10 text-orange-500 hover:bg-orange-500/20"
}

const jobStatusColors = {
  pending: "bg-yellow-500/10 text-yellow-500 hover:bg-yellow-500/20",
  processing: "bg-blue-500/10 text-blue-500 hover:bg-blue-500/20",
  completed: "bg-green-500/10 text-green-500 hover:bg-green-500/20",
  error: "bg-red-500/10 text-red-500 hover:bg-red-500/20"
}

interface JobItemProps {
  job: Job
}

export function JobItem({ job }: JobItemProps) {
  const { removeJob, moveJobToTop, moveJobToBottom, selectJob } = useJobQueue()
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: job.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  const JobTypeIcon = jobTypeIcons[job.type]

  // Helper function to get language label from value
  const getLanguageLabel = (value: string) => {
    const language = LANGUAGES.find(lang => lang.value === value)
    return language ? language.label : value
  }

  // Helper function to extract file names from paths
  const getFileName = (path: string) => {
    if (path.startsWith('blob:')) {
      // For blob URLs, try to get the name from the job
      return path.split('/').pop() || path
    }
    // For local files or URLs, get the last part of the path
    const segments = path.split(/[\/\\]/)
    return segments[segments.length - 1] || path
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "flex items-center gap-2 p-3 bg-card/50 backdrop-blur-sm rounded-lg border shadow-sm",
        "transition-all duration-200 hover:shadow-md hover:scale-[1.01]",
        isDragging && "opacity-50",
        job.selected && "ring-2 ring-primary"
      )}
    >
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <button {...attributes} {...listeners} className="cursor-grab active:cursor-grabbing hover:text-primary transition-colors">
              <GripVertical className="h-5 w-5" />
            </button>
          </TooltipTrigger>
          <TooltipContent>
            <p>Drag to reorder</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      {job.source === "local" ? (
        <FileVideo className="h-5 w-5 text-primary" />
      ) : (
        <LinkIcon className="h-5 w-5 text-primary" />
      )}

      <JobTypeIcon className="h-5 w-5 text-primary" />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">
            {job.name}
          </span>
          <Badge variant="outline" className={cn(
            "text-xs font-normal transition-colors",
            jobStatusColors[job.status || "pending"]
          )}>
            {job.status || "pending"}
          </Badge>
          <Badge variant="outline" className={cn(
            "text-xs font-normal transition-colors",
            jobTypeColors[job.type]
          )}>
            {jobTypeLabels[job.type]}
          </Badge>
          {(job.type === 'shorts' || job.type === 'subtitle') && job.config && (
            <Badge variant="outline" className="text-xs font-normal bg-violet-500/10 text-violet-500 hover:bg-violet-500/20">
              {job.config.translateSubtitles
                ? `Translated → ${getLanguageLabel(job.config.targetLanguage || 'en')}`
                : 'Original'
              }
            </Badge>
          )}
          {job.type === 'translation' && job.config && (
            <Badge variant="outline" className="text-xs font-normal bg-violet-500/10 text-violet-500 hover:bg-violet-500/20">
              {`Translated → ${getLanguageLabel(job.config.targetLanguage || 'en')}`}
            </Badge>
          )}
          {job.type === 'merge' && job.config && (
            <Badge variant="outline" className="text-xs font-normal bg-teal-500/10 text-teal-500 hover:bg-teal-500/20">
              {`${getFileName(job.url)} → ${getFileName(job.config.subtitleUrl)}`}
            </Badge>
          )}
        </div>
        {job.error && (
          <p className="text-xs text-destructive mt-1 truncate">
            Error: {job.error}
          </p>
        )}
      </div>

      <div className="flex items-center gap-1">
        {job.status === 'pending' && (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => selectJob(job.id)}
            className={cn(
              "text-muted-foreground transition-colors",
              job.selected ? "text-primary" : "hover:text-primary"
            )}
          >
            <Settings className="h-4 w-4" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => moveJobToTop(job.id)}
          className="text-muted-foreground hover:text-primary transition-colors"
        >
          <ChevronsUp className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => moveJobToBottom(job.id)}
          className="text-muted-foreground hover:text-primary transition-colors"
        >
          <ChevronsDown className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => removeJob(job.id)}
          className="text-muted-foreground hover:text-destructive transition-colors"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}