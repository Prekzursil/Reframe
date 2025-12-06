const express = require('express');
const router = express.Router();
const { requireUser } = require('./middleware/auth');
const { validateUrl } = require('../controllers/videoController');
const { getVideoMetadata } = require('../controllers/videoMetadataController');

// Development-friendly endpoint that doesn't require authentication
router.post('/validate', (req, res, next) => {
  console.log('Request received at /videos/validate with body:', req.body);
  validateUrl(req, res);
});

// Endpoint to fetch video metadata
router.post('/metadata', (req, res, next) => {
  console.log('Request received at /videos/metadata with body:', req.body);
  getVideoMetadata(req, res);
});

module.exports = router;