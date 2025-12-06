import logging

# Configure a logger for this module
logger = logging.getLogger(__name__)

def format_ass_time(seconds: float) -> str:
    """Converts seconds (float) to ASS time format H:MM:SS.cc"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int((seconds - int(seconds)) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"

def generate_ass_subtitles(transcription_segments, style_options=None):
    """
    Generates subtitles in ASS format with word-by-word karaoke-style highlighting.
    transcription_segments should be a list of segments, where each segment has 'words'.
    Each word in 'words' should have 'word', 'start', 'end'.
    """
    default_style_options = {
        "Fontname": "Arial",
        "Fontsize": "28",
        "PrimaryColour": "&H00FFFFFF",  # White
        "SecondaryColour": "&H000000FF", # Red (for karaoke highlight)
        "OutlineColour": "&H00000000",  # Black
        "BackColour": "&H80000000",     # Semi-transparent black (for background box)
        "Bold": "0", # Default to not bold
        "Italic": "0", # Default to not italic
        "Underline": "0",
        "StrikeOut": "0",
        "ScaleX": "100",
        "ScaleY": "100",
        "Spacing": "0",
        "Angle": "0",
        "BorderStyle": "3", # Outline + drop shadow
        "Outline": "1.5",
        "Shadow": "0.75",
        "Alignment": "2",  # Bottom center
        "MarginL": "10",
        "MarginR": "10",
        "MarginV": "15", # Margin from bottom
        "Encoding": "1" # Default to 1 (System default)
    }
    
    current_styles = default_style_options.copy()
    if style_options is not None:
        current_styles.update(style_options)

    ass_header = f"""[Script Info]
Title: Generated Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 384
PlayResY: 288

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{current_styles['Fontname']},{current_styles['Fontsize']},{current_styles['PrimaryColour']},{current_styles['SecondaryColour']},{current_styles['OutlineColour']},{current_styles['BackColour']},{current_styles['Bold']},{current_styles['Italic']},{current_styles['Underline']},{current_styles['StrikeOut']},{current_styles['ScaleX']},{current_styles['ScaleY']},{current_styles['Spacing']},{current_styles['Angle']},{current_styles['BorderStyle']},{current_styles['Outline']},{current_styles['Shadow']},{current_styles['Alignment']},{current_styles['MarginL']},{current_styles['MarginR']},{current_styles['MarginV']},{current_styles['Encoding']}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    ass_events = []
    for segment in transcription_segments:
        if not segment.get('words'):
            # If no word timings, just put the whole segment text
            start_time_str = format_ass_time(segment['start'])
            end_time_str = format_ass_time(segment['end'])
            text = segment.get('text', '').strip() # Ensure text exists
            if text:
                ass_events.append(f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{text}")
            continue

        # Build line with karaoke tags for each word
        line_text_parts = []
        
        # Ensure 'words' is not empty and contains valid data
        if not segment['words'] or not isinstance(segment['words'], list) or not all(isinstance(w, dict) for w in segment['words']):
            logger.warning(f"Segment has invalid 'words' data: {segment.get('words')}")
            # Fallback to segment text if words are malformed
            start_time_str = format_ass_time(segment['start'])
            end_time_str = format_ass_time(segment['end'])
            text = segment.get('text', '').strip()
            if text:
                ass_events.append(f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{text}")
            continue

        segment_start_time = segment['words'][0].get('start', segment['start'])
        segment_end_time = segment['words'][-1].get('end', segment['end'])

        for i, word_info in enumerate(segment['words']):
            word_text = word_info.get('word', '')
            word_start = word_info.get('start')
            word_end = word_info.get('end')

            if word_start is None or word_end is None:
                logger.warning(f"Word missing start/end time: {word_info}")
                line_text_parts.append(word_text.strip()) # Add word without timing
                continue
            
            # Duration of the word highlight in centiseconds
            duration_cs = max(1, int((word_end - word_start) * 100)) # Ensure at least 1cs
            
            line_text_parts.append(f"{{\\k{duration_cs}}}{word_text.strip()}")
        
        full_line_text = "".join(line_text_parts)
        if full_line_text:
            start_time_str = format_ass_time(segment_start_time)
            # Ensure segment_end_time is at least segment_start_time
            actual_end_time = max(segment_start_time, segment_end_time)
            end_time_str = format_ass_time(actual_end_time)
            ass_events.append(f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{full_line_text}")
            
    return ass_header + "\n".join(ass_events)

def format_srt_time(seconds: float) -> str:
    """Converts seconds (float) to SRT time format HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

def segments_to_srt_content(transcription_segments) -> str:
    """
    Converts a list of transcription segments to SRT subtitle format content.
    Each segment should be a dictionary with 'start', 'end', and 'text'.
    """
    srt_blocks = []
    for i, segment in enumerate(transcription_segments):
        sequence_number = i + 1
        start_time_str = format_srt_time(segment['start'])
        end_time_str = format_srt_time(segment['end'])
        text = segment.get('text', '').strip()

        # SRT blocks are separated by a blank line. Each block ends with a newline.
        srt_blocks.append(f"{sequence_number}\n{start_time_str} --> {end_time_str}\n{text}\n")
        
    return "\n".join(srt_blocks)
