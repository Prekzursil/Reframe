import { createContext, useContext, useState, ReactNode } from "react"

export type JobType = 'shorts' | 'subtitle' | 'translation' | 'merge'
export type JobStatus = 'pending' | 'processing' | 'completed' | 'error'

export interface Job {
  id: string
  name: string
  type: JobType
  source: 'local' | 'url'
  url: string
  status?: JobStatus
  error?: string
  progress?: number
  outputFolder?: string
  config?: any
  selected?: boolean
}

interface JobQueueContextType {
  jobs: Job[]
  addJob: (job: Omit<Job, 'id' | 'status'>) => void
  removeJob: (id: string) => void
  reorderJobs: (jobs: Job[]) => void
  updateJob: (id: string, updates: Partial<Job>) => void
  moveJobToTop: (id: string) => void
  moveJobToBottom: (id: string) => void
  selectJob: (id: string) => void
  startProcessing: (jobs: Job[]) => void
}

const JobQueueContext = createContext<JobQueueContextType | null>(null)

export function JobQueueProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([])

  const addJob = (job: Omit<Job, 'id' | 'status'>) => {
    const newJob = {
      ...job,
      id: Math.random().toString(36).substr(2, 9),
      status: 'pending' as JobStatus,
      selected: false
    }
    setJobs(prev => [...prev, newJob])
  }

  const simulateJobProcessing = (jobId: string) => {
    // Update to processing after 1 second
    setTimeout(() => {
      updateJob(jobId, { status: 'processing' })

      // Simulate progress updates
      let progress = 0
      const progressInterval = setInterval(() => {
        progress += 10
        if (progress <= 100) {
          updateJob(jobId, { progress })
        } else {
          clearInterval(progressInterval)
          // 90% chance of success, 10% chance of error
          const success = Math.random() > 0.1
          updateJob(jobId, {
            status: success ? 'completed' : 'error',
            error: success ? undefined : 'Failed to process video'
          })
        }
      }, 1000)
    }, 1000)
  }

  const startProcessing = (jobsToProcess: Job[]) => {
    jobsToProcess.forEach(job => {
      if (job.status === 'pending') {
        simulateJobProcessing(job.id)
      }
    })
  }

  const removeJob = (id: string) => {
    setJobs(prev => prev.filter(job => job.id !== id))
  }

  const reorderJobs = (newJobs: Job[]) => {
    setJobs(newJobs)
  }

  const updateJob = (id: string, updates: Partial<Job>) => {
    setJobs(prev => prev.map(job =>
      job.id === id ? { ...job, ...updates } : job
    ))
  }

  const moveJobToTop = (id: string) => {
    setJobs(prev => {
      const job = prev.find(j => j.id === id)
      if (!job) return prev
      return [job, ...prev.filter(j => j.id !== id)]
    })
  }

  const moveJobToBottom = (id: string) => {
    setJobs(prev => {
      const job = prev.find(j => j.id === id)
      if (!job) return prev
      return [...prev.filter(j => j.id !== id), job]
    })
  }

  const selectJob = (id: string) => {
    setJobs(prev => prev.map(job => ({
      ...job,
      selected: job.id === id
    })))
  }

  return (
    <JobQueueContext.Provider value={{
      jobs,
      addJob,
      removeJob,
      reorderJobs,
      updateJob,
      moveJobToTop,
      moveJobToBottom,
      selectJob,
      startProcessing
    }}>
      {children}
    </JobQueueContext.Provider>
  )
}

export function useJobQueue() {
  const context = useContext(JobQueueContext)
  if (!context) {
    throw new Error("useJobQueue must be used within a JobQueueProvider")
  }
  return context
}