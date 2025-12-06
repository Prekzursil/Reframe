const path = require('path');
const fs = require('fs').promises;
const { exec } = require('child_process');
const util = require('util');
const execPromise = util.promisify(exec);
const ProcessingJob = require('./models/ProcessingJob');
const os = require('os');
const axios = require('axios');
const ffmpeg = require('fluent-ffmpeg');
const { analyzeTranscript } = require('./services/llmService');

// Helper function to ensure a directory exists
const ensureDir = async (dirPath) => {
  try {
    await fs.access(dirPath);
  } catch (error) {
    await fs.mkdir(dirPath, { recursive: true });
  }
};

// Helper function to download video from URL
const downloadVideo = async (url, outputPath) => {
  console.log(`Downloading video from ${url} to ${outputPath}`);

  const writer = require('fs').createWriteStream(outputPath);
  const response = await axios({
    url,
    method: 'GET',
    responseType: 'stream',
  });

  response.data.pipe(writer);

  return new Promise((resolve, reject) => {
    writer.on('finish', resolve);
    writer.on('error', reject);
  });
};

// Get video duration using FFmpeg
const getVideoDuration = (filePath) => {
  return new Promise((resolve, reject) => {
    ffmpeg.ffprobe(filePath, (err, metadata) => {
      if (err) return reject(err);
      resolve(metadata.format.duration);
    });
  });
};

// Create clip from video using FFmpeg
const createClip = async (videoPath, outputPath, start, end) => {
  return new Promise((resolve, reject) => {
    ffmpeg(videoPath)
      .setStartTime(start)
      .setDuration(end - start)
      .output(outputPath)
      .on('end', resolve)
      .on('error', reject)
      .run();
  });
};

// Extract audio and transcribe using local whisper model
const transcribeAudio = async (audioPath) => {
  try {
    // First convert to WAV format
    const wavPath = `${audioPath}.wav`;
    await new Promise((resolve, reject) => {
      ffmpeg(audioPath)
        .output(wavPath)
        .audioCodec('pcm_s16le')
        .audioFrequency(16000)
        .on('end', resolve)
        .on('error', reject)
        .run();
    });

    // Use local whisper model (assuming it's in ./whisper-models)
    const modelPath = path.join(__dirname, 'whisper-models', 'ggml-base.en.bin');
    const { stdout } = await execPromise(`whisper ${wavPath} --model ${modelPath} --output_format json`);
    const result = JSON.parse(stdout);
    return result.segments.map(segment => ({
      start: segment.start,
      end: segment.end,
      text: segment.text
    }));
  } catch (error) {
    console.error('Error transcribing audio:', error);
    throw new Error('Failed to transcribe audio');
  }
};

// Generate intelligent segments using LLM analysis
const generateSegments = async (transcript, videoDuration, minDuration, maxDuration, prompt) => {
  try {
    // Analyze transcript with LLM
    const analysis = await analyzeTranscript({
      transcript,
      minDuration,
      maxDuration,
      prompt
    });

    return analysis.segments.map(segment => ({
      start: segment.startTime,
      end: segment.endTime,
      title: segment.title,
      summary: segment.summary
    }));
  } catch (error) {
    console.error('Error generating segments with LLM:', error);
    // Fallback to simple segmentation
    const segments = [];
    const segmentDuration = Math.min(maxDuration, Math.max(minDuration, 30));
    let currentTime = 0;

    while (currentTime < videoDuration) {
      const segmentEnd = Math.min(currentTime + segmentDuration, videoDuration);
      segments.push({
        start: currentTime,
        end: segmentEnd,
        title: `Clip ${segments.length + 1}`,
        summary: `Video segment from ${Math.floor(currentTime)}s to ${Math.floor(segmentEnd)}s`
      });
      currentTime = segmentEnd;
    }

    return segments;
  }
};

/**
 * Process a video and break it into clips of specified duration
 */
const processVideo = async (jobId) => {
  try {
    // Get job details
    const job = await ProcessingJob.findById(jobId);
    if (!job) {
      throw new Error('Processing job not found');
    }

    // Update job status to processing
    job.status = 'processing';
    await job.save();

    console.log(`Starting processing for job ${jobId}`);

    // Create temporary work directory
    const workDir = path.join(os.tmpdir(), `shorts-maker-${jobId}`);
    await ensureDir(workDir);

    // Create output directory
    const outputDir = path.join(workDir, 'output');
    await ensureDir(outputDir);

    // 1. Get the source video
    const videoPath = path.join(workDir, 'source.mp4');
    if (job.sourceType === 'url') {
      await downloadVideo(job.sourceUrl, videoPath);
    } else {
      try {
        await fs.copyFile(job.sourceUrl, videoPath);
      } catch (error) {
        throw new Error(`Could not access local file: ${error.message}`);
      }
    }

    // 2. Extract audio and transcribe
    const audioPath = path.join(workDir, 'audio.wav');
    await new Promise((resolve, reject) => {
      ffmpeg(videoPath)
        .output(audioPath)
        .audioCodec('pcm_s16le')
        .audioFrequency(16000)
        .on('end', resolve)
        .on('error', reject)
        .run();
    });

    const transcript = await transcribeAudio(audioPath);

    // 3. Generate intelligent segments using LLM
    const segments = await generateSegments(
      transcript,
      await getVideoDuration(videoPath),
      job.duration.min,
      job.duration.max,
      job.prompt
    );

    // 4. Create clips based on the segments
    const clips = [];
    for (let i = 0; i < segments.length; i++) {
      const segment = segments[i];
      const clipFileName = `clip_${i + 1}.mp4`;
      const clipPath = path.join(outputDir, clipFileName);

      await createClip(videoPath, clipPath, segment.start, segment.end);

      clips.push({
        title: segment.title,
        path: `/processed/${jobId}/clips/${clipFileName}`,
        start: segment.start,
        end: segment.end,
        duration: segment.end - segment.start,
        summary: segment.summary
      });
    }

    // 5. Update job with results
    job.status = 'completed';
    job.clips = clips;
    await job.save();

    console.log(`Completed processing for job ${jobId} with ${clips.length} clips`);
    return job;
  } catch (error) {
    console.error(`Error processing video for job ${jobId}:`, error);

    // Update job with error
    const job = await ProcessingJob.findById(jobId);
    if (job) {
      job.status = 'failed';
      job.error = error.message;
      await job.save();
    }

    throw error;
  }
};

/**
 * Get the status of a processing job
 */
const getProcessingStatus = async (jobId) => {
  const job = await ProcessingJob.findById(jobId);
  if (!job) {
    throw new Error('Processing job not found');
  }

  return {
    id: job._id,
    status: job.status,
    progress: job.status === 'completed' ? 100 :
             job.status === 'failed' ? 0 :
             job.status === 'processing' ? Math.floor(Math.random() * 80) + 10 : 0,
    clips: job.clips,
    error: job.error,
    sourceUrl: job.sourceUrl,
    createdAt: job.createdAt,
    updatedAt: job.updatedAt
  };
};

module.exports = {
  processVideo,
  getProcessingStatus
};