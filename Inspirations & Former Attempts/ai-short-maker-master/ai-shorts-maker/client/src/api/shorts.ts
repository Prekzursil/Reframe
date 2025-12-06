import api from './api';
import { validateVideoUrl } from './videos';

// Description: Fetch video metadata (title, duration, etc.)
// Endpoint: POST /api/videos/metadata
// Request: { url: string }
// Response: { success: boolean, metadata: { title: string, description: string, duration: number, thumbnail: string, platform: string, videoId: string } }
export const fetchVideoMetadata = async (url: string) => {
  console.log('Frontend: Attempting to fetch metadata for URL:', url);
  // First validate the URL
  try {
    const validationResult = await validateVideoUrl(url);
    console.log('Frontend: Validation result:', validationResult);

    if (!validationResult.isValid) {
      throw new Error('Invalid video URL');
    }

    // Make the actual API call to fetch metadata
    try {
      const response = await api.post('/videos/metadata', { url });
      console.log('Frontend: Metadata response:', response.data);
      return response.data.metadata;
    } catch (error) {
      console.error('Frontend: Error fetching metadata:', error);
      throw new Error(error.response?.data?.error || error.message);
    }
  } catch (error) {
    console.error('Frontend: Validation error or metadata fetch error:', error);
    throw new Error(error.response?.data?.error || error.message);
  }
};

// Description: Process videos into shorter clips
// Endpoint: POST /api/shorts/process
// Request: {
//   videos: Array<{ path: string; type: 'local' | 'url' }>;
//   prompt: string;
//   duration: { min: number; max: number };
//   initialWhisperModel: string;
//   subtitles: boolean;
//   originalLanguage: string;
//   burnSubtitles: boolean;
//   saveSrtSeparately: boolean;
//   translateSubtitles: boolean;
//   targetLanguage?: string;
//   translateTitle: boolean;
//   saveOriginalSrt: boolean;
//   saveTranslatedSrt: boolean;
//   subtitleWhisperModel: string;
//   subtitleStyle?: {
//     fontSize: number;
//     fontColor: string;
//     highlightColor: string;
//     backgroundColor: string;
//     opacity: number;
//   };
// }
// Response: {
//   success: boolean,
//   message: string,
//   jobs: Array<{
//     id: string,
//     status: string,
//     sourceUrl: string
//   }>
// }
export const processVideos = async (data: {
  videos: Array<{ path: string; type: 'local' | 'url' }>;
  prompt: string;
  duration: { min: number; max: number };
  initialWhisperModel: string;
  subtitles: boolean;
  originalLanguage: string;
  burnSubtitles: boolean;
  saveSrtSeparately: boolean;
  translateSubtitles: boolean;
  targetLanguage?: string;
  translateTitle: boolean;
  saveOriginalSrt: boolean;
  saveTranslatedSrt: boolean;
  subtitleWhisperModel: string;
  subtitleStyle?: {
    fontSize: number;
    fontColor: string;
    highlightColor: string;
    backgroundColor: string;
    opacity: number;
  };
  outputFolder?: string;
}) => {
  try {
    const response = await api.post('/shorts/process', data);
    return response.data;
  } catch (error) {
    console.error('Error processing videos:', error);
    throw new Error(error.response?.data?.error || error.message);
  }
};

// Description: Get processing status
// Endpoint: GET /api/shorts/status/:jobId
// Request: {}
// Response: {
//   success: boolean,
//   job: {
//     id: string,
//     status: string,
//     progress: number,
//     sourceUrl: string,
//     createdAt: string,
//     updatedAt: string,
//     clips: Array<{
//       title: string,
//       path: string,
//       start: number,
//       end: number,
//       duration: number,
//       subtitlePath: string | null,
//       translatedSubtitlePath: string | null
//     }>,
//     error: string | null
//   }
// }
export const getProcessingStatus = async (jobId: string) => {
  try {
    const response = await api.get(`/shorts/status/${jobId}`);
    return response.data;
  } catch (error) {
    console.error('Error getting processing status:', error);
    throw new Error(error.response?.data?.error || error.message);
  }
};

// Rest of the file remains unchanged
export const generateSubtitles = (data: {
  videos: Array<{ path: string }>;
  language?: string;
  whisperModel?: string;
}) => {
  // Mocking the response
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        success: true,
        subtitles: [
          { videoPath: '/videos/presentation.mp4', subtitlePath: '/subtitles/presentation.srt' },
          { videoPath: '/videos/interview.mp4', subtitlePath: '/subtitles/interview.srt' },
        ],
      });
    }, 1500);
  });
};

// Description: Translate subtitles
// Endpoint: POST /api/subtitles/translate
// Request: { subtitles: Array<{ path: string }>, targetLanguage: string }
// Response: { success: boolean, translations: Array<{ originalPath: string, translatedPath: string }> }
export const translateSubtitles = (data: {
  subtitles: Array<{ path: string }>;
  targetLanguage: string;
}) => {
  // Mocking the response
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        success: true,
        translations: [
          { originalPath: '/subtitles/presentation.srt', translatedPath: '/subtitles/presentation_es.srt' },
          { originalPath: '/subtitles/interview.srt', translatedPath: '/subtitles/interview_es.srt' },
        ],
      });
    }, 1000);
  });
};

// Description: Merge subtitles with video
// Endpoint: POST /api/subtitles/merge
// Request: { videos: Array<{ videoPath: string, subtitlePath: string }> }
// Response: { success: boolean, mergedVideos: Array<{ originalPath: string, mergedPath: string }> }
export const mergeSubtitles = (data: {
  videos: Array<{ videoPath: string; subtitlePath: string }>;
}) => {
  // Mocking the response
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        success: true,
        mergedVideos: [
          { originalPath: '/videos/presentation.mp4', mergedPath: '/videos/presentation_subtitled.mp4' },
          { originalPath: '/videos/interview.mp4', mergedPath: '/videos/interview_subtitled.mp4' },
        ],
      });
    }, 1500);
  });
};