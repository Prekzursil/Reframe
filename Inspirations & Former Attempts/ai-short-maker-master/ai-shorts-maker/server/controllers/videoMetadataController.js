const youtubedl = require('youtube-dl-exec');

/**
 * Retrieves metadata for a video URL from supported platforms
 * @param {Object} req - Express request object with url in body
 * @param {Object} res - Express response object
 */
const getVideoMetadata = async (req, res) => {
  try {
    const { url } = req.body;

    if (!url) {
      console.log('Metadata fetch failed: URL is required');
      return res.status(400).json({
        success: false,
        error: 'URL is required'
      });
    }

    console.log(`Fetching metadata for video URL: ${url}`);

    try {
      // Use youtube-dl to fetch basic video metadata
      const metadata = await youtubedl(url, {
        dumpSingleJson: true,
        noCheckCertificates: true,
        noWarnings: true,
        preferFreeFormats: true
      });

      const simplifiedMetadata = {
        title: metadata.title,
        description: metadata.description,
        duration: metadata.duration,
        thumbnail: metadata.thumbnail,
        uploadDate: metadata.upload_date,
        viewCount: metadata.view_count,
        platform: metadata.extractor,
        formats: metadata.formats?.map(f => ({
          formatId: f.format_id,
          url: f.url,
          ext: f.ext,
          filesize: f.filesize,
          resolution: `${f.width}x${f.height}`
        })) || []
      };

      console.log(`Successfully fetched metadata for: ${simplifiedMetadata.title}`);
      return res.json({
        success: true,
        metadata: simplifiedMetadata
      });
    } catch (error) {
      console.error('Error fetching video metadata:', error);
      return res.status(400).json({
        success: false,
        error: 'Failed to fetch video metadata. The URL might be invalid or unsupported.'
      });
    }
  } catch (error) {
    console.error('Error in getVideoMetadata controller:', error);
    return res.status(500).json({
      success: false,
      error: error.message || 'Failed to fetch video metadata'
    });
  }
};

module.exports = {
  getVideoMetadata
};