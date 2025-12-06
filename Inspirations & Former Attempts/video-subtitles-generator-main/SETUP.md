# Quick Setup Guide

## Prerequisites

1. **Install System Dependencies**

   macOS:
   ```bash
   brew install ffmpeg imagemagick
   ```

   Ubuntu/Debian:
   ```bash
   sudo apt-get install ffmpeg imagemagick
   ```

2. **Python 3.8 or higher**
   ```bash
   python --version
   ```

## Installation Steps

1. **Navigate to project directory**
   ```bash
   cd /Users/joopsnijder/Projects/video_subtitles
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Quick Test

```bash
# Activate virtual environment
source .venv/bin/activate

# Test the script
python generate_subtitles.py --help

# Process a video (replace with your actual video file)
python generate_subtitles.py your_video.mp4
```

## Common Issues

### ImageMagick Policy Error

If you get a policy error about TEXT, edit ImageMagick's policy.xml:

```bash
# Find the policy file
convert -list policy

# Edit the file and comment out or change this line:
# <policy domain="path" rights="none" pattern="@*"/>
# to:
# <policy domain="path" rights="read|write" pattern="@*"/>
```

### MoviePy Import Errors

The script uses the latest MoviePy version with updated imports. If you see import errors, make sure you have the correct version installed:

```bash
pip install --upgrade moviepy
```

### Memory Issues

If processing large videos causes memory issues:
- Use a smaller Whisper model: `--model tiny` or `--model small`
- Process shorter video clips
- Close other applications

## Next Steps

- Read [README.md](README.md) for detailed documentation
- Check [example_usage.py](example_usage.py) for programmatic usage examples
- Edit [config.json](config.json) to customize default settings
