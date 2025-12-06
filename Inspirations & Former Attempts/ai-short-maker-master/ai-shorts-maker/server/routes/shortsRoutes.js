const express = require('express');
const router = express.Router();
const { requireUser } = require('./middleware/auth');
const {
  processVideoController,
  getProcessingStatus
} = require('../controllers/videoProcessingController');

// Process videos into shorts
router.post('/process', requireUser, processVideoController);

// Get processing status
router.get('/status/:jobId', requireUser, getProcessingStatus);

// Generate subtitles
router.post('/subtitles/generate', requireUser, async (req, res) => {
  try {
    res.json({ success: true, message: 'Subtitle generation started' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Translate subtitles
router.post('/subtitles/translate', requireUser, async (req, res) => {
  try {
    res.json({ success: true, message: 'Subtitle translation started' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Merge subtitles with video
router.post('/subtitles/merge', requireUser, async (req, res) => {
  try {
    res.json({ success: true, message: 'Subtitle merging started' });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

module.exports = router;