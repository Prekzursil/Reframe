const mongoose = require('mongoose');

const clipSchema = new mongoose.Schema({
  title: String,
  path: String,
  start: Number,
  end: Number,
  duration: Number,
  summary: String,
  subtitlePath: String,
  translatedSubtitlePath: String
});

const subtitleStyleSchema = new mongoose.Schema({
  fontSize: { type: Number, default: 24 },
  fontColor: { type: String, default: '#FFFFFF' },
  highlightColor: { type: String, default: '#FF3B30' },
  backgroundColor: { type: String, default: '#000000' },
  opacity: { type: Number, default: 80 },
  fontFamily: { type: String, default: 'Arial' }
});

const processingJobSchema = new mongoose.Schema({
  userId: { type: mongoose.Schema.Types.ObjectId, ref: 'User', required: true },
  sourceType: { type: String, enum: ['url', 'local'], required: true },
  sourceUrl: { type: String, required: true },
  prompt: String,
  duration: {
    min: { type: Number, required: true },
    max: { type: Number, required: true }
  },
  status: { 
    type: String, 
    enum: ['pending', 'processing', 'completed', 'failed'],
    default: 'pending'
  },
  progress: { type: Number, default: 0 },
  clips: [clipSchema],
  error: String,
  subtitles: { type: Boolean, default: false },
  subtitleStyle: subtitleStyleSchema,
  translateSubtitles: { type: Boolean, default: false },
  targetLanguage: { type: String, default: 'en' },
  outputFolder: { type: String, required: true },
  createdAt: { type: Date, default: Date.now },
  updatedAt: { type: Date, default: Date.now }
});

// Update timestamp on save
processingJobSchema.pre('save', function(next) {
  this.updatedAt = Date.now();
  next();
});

// Add text index for search
processingJobSchema.index({
  'clips.title': 'text',
  'clips.summary': 'text',
  prompt: 'text'
});

const ProcessingJob = mongoose.model('ProcessingJob', processingJobSchema);

module.exports = ProcessingJob;