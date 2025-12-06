import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragStartEvent,
  DragEndEvent,
} from "@dnd-kit/core"
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { VideoItem } from "./VideoItem"
import { ScrollArea, ScrollBar } from "./ui/scroll-area"
import type { VideoItem as VideoItemType } from "@/types/video"
import { defaultVideoConfig } from "@/types/video"
import { useJobQueue } from "@/contexts/JobQueueContext"
import { JobType } from "@/contexts/JobQueueContext"

interface VideoListProps {
  videos: VideoItemType[]
  onVideosReorder: (videos: VideoItemType[]) => void
  onVideoRemove: (id: string) => void
  onVideoSelect: (video: VideoItemType) => void
  isProcessing?: boolean
  jobType?: JobType
}

export function VideoList({
  videos,
  onVideosReorder,
  onVideoRemove,
  onVideoSelect,
  isProcessing,
  jobType = 'shorts'
}: VideoListProps) {
  const { addJob } = useJobQueue()

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 5,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  const handleDragStart = (event: DragStartEvent) => {
    event.stopPropagation?.()
  }

  const handleDragEnd = (event: DragEndEvent) => {
    event.stopPropagation?.()

    const { active, over } = event
    if (over && active.id !== over.id) {
      const oldIndex = videos.findIndex((video) => video.id === active.id)
      const newIndex = videos.findIndex((video) => video.id === over.id)
      onVideosReorder(arrayMove(videos, oldIndex, newIndex))
    }
  }

  const handleAddToQueue = (video: VideoItemType) => {
    const config = video.config || { ...defaultVideoConfig }
    addJob({
      name: video.title || video.name,
      type: jobType,
      source: video.type,
      url: video.url,
      config
    })
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-background/95 backdrop-blur-sm">
        <ScrollArea className="h-[400px] w-full">
          <div className="p-4">
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragStart={handleDragStart}
              onDragEnd={handleDragEnd}
            >
              <SortableContext items={videos} strategy={verticalListSortingStrategy}>
                <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                  {videos.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8">
                      No videos added yet
                    </div>
                  ) : (
                    videos.map((video) => (
                      <VideoItem
                        key={video.id}
                        video={video}
                        onRemove={onVideoRemove}
                        onSelect={onVideoSelect}
                        onAddToQueue={handleAddToQueue}
                        isProcessing={isProcessing}
                      />
                    ))
                  )}
                </div>
              </SortableContext>
            </DndContext>
          </div>
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
      </div>
      <div className="text-sm text-muted-foreground">
        {videos.length} video{videos.length !== 1 ? 's' : ''} in list
      </div>
    </div>
  )
}