import api from './api';

// Description: Validate video URL
// Endpoint: POST /api/videos/validate
// Request: { url: string }
// Response: { success: boolean, isValid: boolean, platform?: string, videoId?: string, error?: string }
export const validateVideoUrl = async (url: string) => {
  console.log('Frontend: Attempting to validate URL:', url);
  try {
    const response = await api.post('/videos/validate', { url });
    console.log('Frontend: URL validation response:', response.data);
    return response.data;
  } catch (error) {
    console.error('Frontend: Error validating video URL:', error);
    console.error('Frontend: Error response:', error.response?.data);
    throw new Error(error?.response?.data?.error || error.message);
  }
};