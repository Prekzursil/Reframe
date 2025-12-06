const { Groq } = require('groq-sdk');
const { v4: uuidv4 } = require('uuid');
const ProcessingJob = require('../models/ProcessingJob');

const groq = new Groq({
  apiKey: process.env.GROQ_API_KEY
});

// Validate API key and model
if (!process.env.GROQ_API_KEY || process.env.GROQ_API_KEY.includes('YOUR_')) {
  throw new Error('Groq API key not configured in .env file');
}
if (!fs.existsSync(path.join(__dirname, '../whisper-models/ggml-base.en.bin'))) {
  throw new Error('Whisper model file not found');
}

/**
 * Analyze video transcript and generate optimal segments
 */
const analyzeTranscript = async ({ transcript, minDuration, maxDuration, prompt }) => {
  try {
    // Prepare the segments for analysis
    const transcriptText = transcript.map(segment => 
      `[${segment.start.toFixed(2)}-${segment.end.toFixed(2)}s]: ${segment.text}`
    ).join('\n');

    // Create the analysis prompt
    const analysisPrompt = `
    Analyze this video transcript and break it into optimal segments for short videos.
    Each segment should be between ${minDuration} and ${maxDuration} seconds.
    ${prompt ? `Additional requirements: ${prompt}` : ''}
    
    Transcript:
    ${transcriptText}
    
    Return your analysis in JSON format with this structure:
    {
      "segments": [
        {
          "startTime": number,
          "endTime": number,
          "title": string,
          "summary": string
        }
      ]
    }
    `;

    // Get response from Groq
    const response = await groq.chat.completions.create({
      messages: [
        {
          role: "system",
          content: "You are a helpful assistant that analyzes video transcripts and creates optimal segments for short videos."
        },
        {
          role: "user",
          content: analysisPrompt
        }
      ],
      model: "mixtral-8x7b-32768",
      response_format: { type: "json_object" }
    });

    // Parse and return the response
    const result = JSON.parse(response.choices[0].message.content);
    return result;
  } catch (error) {
    console.error('Error analyzing transcript with LLM:', error);
    throw error;
  }
};

module.exports = {
  analyzeTranscript
};