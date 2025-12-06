import { useJobQueue, Job } from "@/contexts/JobQueueContext"
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent
} from "@dnd-kit/core"
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { JobItem } from "./JobItem"
import { ScrollArea } from "./ui/scroll-area"
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "./ui/card"
import { FileDown, Play } from "lucide-react"
import { Progress } from "./ui/progress"
import { Button } from "./ui/button"

export function JobQueue() {
  const { jobs, reorderJobs, startProcessing } = useJobQueue()

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (over && active.id !== over.id) {
      const oldIndex = jobs.findIndex((job) => job.id === active.id)
      const newIndex = jobs.findIndex((job) => job.id === over.id)
      reorderJobs(arrayMove(jobs, oldIndex, newIndex))
    }
  }

  const handleStartProcessing = () => {
    const pendingJobs = jobs.filter(job => job.status === 'pending')
    if (pendingJobs.length > 0) {
      startProcessing(pendingJobs)
    }
  }

  const pendingJobs = jobs.filter(job => job.status === 'pending')
  const activeJobs = jobs.filter(job => job.status === 'processing')
  const completedJobs = jobs.filter(job => job.status === 'completed' || job.status === 'error')

  return (
    <Card className="bg-card/50 backdrop-blur-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileDown className="h-5 w-5" />
          Job Queue {activeJobs.length > 0 && `(${activeJobs.length} active)`}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[300px] pr-4">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext items={jobs} strategy={verticalListSortingStrategy}>
              <div className="space-y-4">
                {jobs.length === 0 ? (
                  <div className="text-center text-muted-foreground py-8">
                    No jobs in queue
                  </div>
                ) : (
                  <>
                    {pendingJobs.length > 0 && (
                      <div className="space-y-2">
                        <h3 className="text-sm font-medium">Pending Jobs</h3>
                        {pendingJobs.map((job) => (
                          <div key={job.id} className="space-y-2">
                            <JobItem job={job} />
                          </div>
                        ))}
                      </div>
                    )}
                    {activeJobs.length > 0 && (
                      <div className="space-y-2">
                        <h3 className="text-sm font-medium">Active Jobs</h3>
                        {activeJobs.map((job) => (
                          <div key={job.id} className="space-y-2">
                            <JobItem job={job} />
                            {job.status === 'processing' && (
                              <Progress value={job.progress} className="h-1" />
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {completedJobs.length > 0 && (
                      <div className="space-y-2">
                        <h3 className="text-sm font-medium">Completed Jobs</h3>
                        {completedJobs.map((job) => (
                          <JobItem key={job.id} job={job} />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            </SortableContext>
          </DndContext>
        </ScrollArea>
      </CardContent>
      {pendingJobs.length > 0 && (
        <CardFooter className="pt-6">
          <Button
            className="w-full bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700"
            onClick={handleStartProcessing}
          >
            <Play className="w-4 h-4 mr-2" />
            Process {pendingJobs.length} Pending Job{pendingJobs.length !== 1 ? 's' : ''}
          </Button>
        </CardFooter>
      )}
    </Card>
  )
}