import { useState, useCallback, useEffect } from "react"
import { useForm } from "react-hook-form"
import { useToast } from "./useToast"
import { useJobQueue } from "@/contexts/JobQueueContext"
import type { VideoItem } from "@/types/video"
import type { FormData } from "@/types/formTypes"
import { defaultFormValues } from "@/types/formTypes"
import { defaultVideoConfig } from "@/types/video"
import { processVideos, getProcessingStatus } from "@/api/shorts"

export function useVideoForm() {
  const { toast } = useToast()
  const { addJob } = useJobQueue()
  const [isLoading, setIsLoading] = useState(false)
  const [activeJobs, setActiveJobs] = useState<Array<{ id: string, status: string }>>([])
  const [pollInterval, setPollInterval] = useState<NodeJS.Timeout | null>(null)

  // Clean up interval on unmount
  useEffect(() => {
    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [pollInterval]);

  const form = useForm<FormData>({
    defaultValues: defaultFormValues
  })

  const onUpdateVideoConfig = useCallback((
    id: string,
    videos: VideoItem[],
    setVideos: (videos: VideoItem[]) => void
  ) => {
    const currentValues = form.getValues()

    const newConfig = {
      prompt: currentValues.prompt,
      minDuration: currentValues.minDuration,
      maxDuration: currentValues.maxDuration,
      initialWhisperModel: currentValues.initialWhisperModel,
      generateSubtitles: currentValues.generateSubtitles,
      originalLanguage: currentValues.originalLanguage,
      burnSubtitles: currentValues.burnSubtitles,
      saveSrtSeparately: currentValues.saveSrtSeparately,
      translateSubtitles: currentValues.translateSubtitles,
      targetLanguage: currentValues.targetLanguage,
      translateTitle: currentValues.translateTitle,
      saveOriginalSrt: currentValues.saveOriginalSrt,
      saveTranslatedSrt: currentValues.saveTranslatedSrt,
      subtitleWhisperModel: currentValues.subtitleWhisperModel,
      subtitleStyle: currentValues.subtitleStyle,
      outputFolder: currentValues.outputFolder
    }

    setVideos(prev => prev.map(video => {
      if (video.id === id) {
        return {
          ...video,
          config: newConfig,
          lastModified: new Date().toISOString()
        }
      }
      return video
    }))
  }, [form])

  const loadVideoConfig = useCallback((video: VideoItem | null) => {
    if (!video) {
      form.reset(defaultFormValues)
      return
    }

    const config = video.config || defaultVideoConfig
    form.reset({
      prompt: config.prompt || "",
      minDuration: config.minDuration || "30",
      maxDuration: config.maxDuration || "60",
      initialWhisperModel: config.initialWhisperModel || "base",
      generateSubtitles: config.generateSubtitles,
      originalLanguage: config.originalLanguage,
      burnSubtitles: config.burnSubtitles,
      saveSrtSeparately: config.saveSrtSeparately,
      translateSubtitles: config.translateSubtitles,
      targetLanguage: config.targetLanguage || "en",
      translateTitle: config.translateTitle,
      saveOriginalSrt: config.saveOriginalSrt,
      saveTranslatedSrt: config.saveTranslatedSrt,
      subtitleWhisperModel: config.subtitleWhisperModel,
      subtitleStyle: config.subtitleStyle,
      outputFolder: config.outputFolder || ""
    })
  }, [form])

  const onUpdateAllVideos = useCallback((videos: VideoItem[], setVideos: (videos: VideoItem[]) => void) => {
    const currentValues = form.getValues()
    const newConfig = {
      prompt: currentValues.prompt,
      minDuration: currentValues.minDuration,
      maxDuration: currentValues.maxDuration,
      initialWhisperModel: currentValues.initialWhisperModel,
      generateSubtitles: currentValues.generateSubtitles,
      originalLanguage: currentValues.originalLanguage,
      burnSubtitles: currentValues.burnSubtitles,
      saveSrtSeparately: currentValues.saveSrtSeparately,
      translateSubtitles: currentValues.translateSubtitles,
      targetLanguage: currentValues.targetLanguage,
      translateTitle: currentValues.translateTitle,
      saveOriginalSrt: currentValues.saveOriginalSrt,
      saveTranslatedSrt: currentValues.saveTranslatedSrt,
      subtitleWhisperModel: currentValues.subtitleWhisperModel,
      subtitleStyle: currentValues.subtitleStyle,
      outputFolder: currentValues.outputFolder
    }

    setVideos(prev => prev.map(video => ({
      ...video,
      config: newConfig,
      lastModified: new Date().toISOString()
    })))
  }, [form])

  const checkJobStatus = async () => {
    if (activeJobs.length === 0) return;

    const updatedJobs = [...activeJobs];
    let allCompleted = true;

    for (let i = 0; i < updatedJobs.length; i++) {
      const job = updatedJobs[i];

      if (job.status !== 'completed' && job.status !== 'failed') {
        try {
          const response = await getProcessingStatus(job.id);
          updatedJobs[i] = {
            id: job.id,
            status: response.job.status
          };

          // Show toast for completed jobs
          if (response.job.status === 'completed' && job.status !== 'completed') {
            toast({
              title: "Processing Complete",
              description: `Job ${job.id} has finished processing with ${response.job.clips.length} clips.`
            });

            // Add job results to job queue
            response.job.clips.forEach(clip => {
              addJob({
                name: clip.title,
                type: 'shorts',
                status: 'completed',
                result: {
                  path: clip.path,
                  duration: clip.duration,
                  subtitlePath: clip.subtitlePath
                }
              });
            });
          }

          // Show toast for failed jobs
          if (response.job.status === 'failed' && job.status !== 'failed') {
            toast({
              variant: "destructive",
              title: "Processing Failed",
              description: response.job.error || "An error occurred during processing."
            });
          }

          if (response.job.status !== 'completed' && response.job.status !== 'failed') {
            allCompleted = false;
          }
        } catch (error) {
          console.error("Error checking job status:", error);
          // Don't update the job status if there was an error checking it
          allCompleted = false;
        }
      }
    }

    setActiveJobs(updatedJobs);

    // Clear interval if all jobs are completed
    if (allCompleted && pollInterval) {
      clearInterval(pollInterval);
      setPollInterval(null);
    }
  };

  const onSubmit = async (
    data: FormData,
    videos: VideoItem[],
    onSuccess?: () => void
  ) => {
    try {
      setIsLoading(true)
      if (videos.length === 0) {
        throw new Error("Please add at least one video")
      }

      if (!data.outputFolder) {
        throw new Error("Please select an output folder")
      }

      // Prepare videos for API
      const formattedVideos = videos.map(video => ({
        path: video.url,
        type: video.type
      }));

      // Process videos
      const response = await processVideos({
        videos: formattedVideos,
        prompt: data.prompt,
        duration: {
          min: parseInt(data.minDuration),
          max: parseInt(data.maxDuration)
        },
        initialWhisperModel: data.initialWhisperModel,
        subtitles: data.generateSubtitles,
        originalLanguage: data.originalLanguage,
        burnSubtitles: data.burnSubtitles,
        saveSrtSeparately: data.saveSrtSeparately,
        translateSubtitles: data.translateSubtitles,
        targetLanguage: data.targetLanguage,
        translateTitle: data.translateTitle,
        saveOriginalSrt: data.saveOriginalSrt,
        saveTranslatedSrt: data.saveTranslatedSrt,
        subtitleWhisperModel: data.subtitleWhisperModel,
        subtitleStyle: data.subtitleStyle,
        outputFolder: data.outputFolder
      });

      if (response.success) {
        toast({
          title: "Success",
          description: `Started processing ${videos.length} video(s)`,
        });

        // Set active jobs and start polling
        setActiveJobs(response.jobs);
        
        if (pollInterval) {
          clearInterval(pollInterval);
        }
        
        const interval = setInterval(checkJobStatus, 5000);
        setPollInterval(interval);

        onSuccess?.();
      } else {
        throw new Error(response.error || "Failed to process videos");
      }
    } catch (error) {
      console.error("Error in onSubmit:", error);
      toast({
        variant: "destructive",
        title: "Error",
        description: error.message || "Failed to process videos",
      });
    } finally {
      setIsLoading(false);
    }
  };

  return {
    form,
    isLoading,
    activeJobs,
    onUpdateVideoConfig,
    onUpdateAllVideos,
    onSubmit,
    loadVideoConfig
  }
}