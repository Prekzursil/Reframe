/**
 * Validates if a URL is a valid video from supported platforms
 * @param {Object} req - Express request object with url in body
 * @param {Object} res - Express response object
 */
const validateUrl = async (req, res) => {
  try {
    const { url } = req.body;

    if (!url) {
      console.log('URL validation failed: URL is required');
      return res.status(400).json({
        success: false,
        error: 'URL is required'
      });
    }

    console.log(`Validating video URL: ${url}`);

    // Basic URL validation for common video platforms
    const videoPatterns = {
      youtube: /^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.be)\/.+/,
      vimeo: /^(https?:\/\/)?(www\.)?(vimeo\.com)\/.+/
    };

    let platform = null;
    let isValid = false;
    let videoId = null;

    // Check if URL matches any supported platform
    for (const [name, pattern] of Object.entries(videoPatterns)) {
      if (pattern.test(url)) {
        platform = name;
        isValid = true;
        // Extract video ID (simplified version)
        try {
          const urlObj = new URL(url);
          if (name === 'youtube') {
            videoId = urlObj.searchParams.get('v') || urlObj.pathname.split('/').pop();
          } else if (name === 'vimeo') {
            videoId = urlObj.pathname.split('/').pop();
          }
        } catch (e) {
          console.warn('Error parsing URL:', e);
        }
        break;
      }
    }

    if (isValid) {
      console.log(`URL validated successfully as ${platform} video with ID: ${videoId}`);
    } else {
      console.log(`URL validation failed: Not a valid video URL`);
    }

    return res.json({
      success: true,
      isValid,
      platform,
      videoId,
      url
    });
  } catch (error) {
    console.error('Error in validateUrl controller:', error);
    return res.status(500).json({
      success: false,
      error: error.message || 'Failed to validate URL'
    });
  }
};

module.exports = {
  validateUrl
};