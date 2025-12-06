const ProcessingJob = require('../models/ProcessingJob');
const { processVideo } = require('../videoProcessor');
const { analyzeTranscript } = require('../services/llmService');

/**
 * Enhanced video processing controller with AI capabilities
 */
const processVideoController = async (req, res) => {
  try {
    const {
      videos,
      prompt,
      duration,
      subtitles,
      subtitleStyle,
      outputFolder
    } = req.body;

    // Input validation
    if (!videos?.length) {
      return res.status(400).json({ 
        success: false,
        error: 'At least one video is required' 
      });
    }

    if (!duration || duration.min >= duration.max) {
      return res.status(400).json({
        success: false,
        error: 'Invalid duration range'
      });
    }

    // Create processing jobs
    const jobs = await Promise.all(videos.map(async (video) => {
      const job = new ProcessingJob({
        userId: req.user._id,
        sourceType: video.type,
        sourceUrl: video.path,
        prompt,
        duration: {
          min: parseInt(duration.min),
          max: parseInt(duration.max)
        },
        subtitles,
        subtitleStyle,
        outputFolder: outputFolder || '/output'
      });

      await job.save();
      return job;
    }));

    // Start processing in background
    jobs.forEach(job => {
      processVideo(job._id).catch(err => {
        console.error(`Background processing error for job ${job._id}:`, err);
      });
    });

    return res.status(201).json({
      success: true,
      message: `Processing ${jobs.length} video(s)`,
      jobs: jobs.map(job => ({
        id: job._id,
        status: job.status,
        sourceUrl: job.sourceUrl
      }))
    });

  } catch (error) {
    console.error('Error in process video controller:', error);
    return res.status(500).json({
      success: false,
      error: error.message || 'Failed to process video'
    });
  }
};

/**
 * Get processing status with enhanced details
 */
const getProcessingStatus = async (req, res) => {
  try {
    const { jobId } = req.params;
    const job = await ProcessingJob.findById(jobId);

    if (!job) {
      return res.status(404).json({
        success: false,
        error: 'Job not found'
      });
    }

    // Authorization check
    if (job.userId.toString() !== req.user._id.toString()) {
      return res.status(403).json({
        success: false,
        error: 'Unauthorized access'
      });
    }

    return res.json({
      success: true,
      job: {
        id: job._id,
        status: job.status,
        progress: job.progress || 0,
        clips: job.clips || [],
        error: job.error,
        sourceUrl: job.sourceUrl,
        createdAt: job.createdAt,
        updatedAt: job.updatedAt
      }
    });

  } catch (error) {
    console.error('Error getting job status:', error);
    return res.status(500).json({
      success: false,
      error: error.message || 'Failed to get status'
    });
  }
};

module.exports = {
  processVideoController,
  getProcessingStatus
};