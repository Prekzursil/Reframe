# Quick Start Guide

## 🎨 Recommended: Professional Style Workflow

### Simpelste Gebruik (Één Command)

```bash
python generate_with_style.py video.mov
```

Dit doet **alles automatisch**:
- ✅ Detecteert video resolutie
- ✅ Extraheert audio (indien nodig)
- ✅ Transcribeert met Whisper "large" model (indien nodig)
- ✅ Hergebruikt bestaande timestamps (bespaart 5+ minuten!)
- ⏸️ **Pauzeert ALTIJD** om transcript te laten bewerken
- ✅ Genereert video met **bold white text, black outline, shadow**
- ✅ Word-by-word **orange highlighting** (aanpasbaar)

**Output:** `video_styled.mp4`

### Met Custom Kleur

```bash
# Cyan highlight (TikTok/Instagram stijl)
python generate_with_style.py video.mov --color cyan

# Yellow highlight
python generate_with_style.py video.mov --color yellow

# Eigen kleur (hex code)
python generate_with_style.py video.mov --color "#FF00FF"
```

### Workflow Voorbeeld

```bash
# Run 1: Eerste keer - transcribeert video (~5-10 minuten)
python generate_with_style.py interview.mov --color orange

# Script output:
# ==============================================================
# Adjusted font size to 97 for 1080x1920 video
# Extracting audio...
# Transcribing with Whisper...
# TRANSCRIPTIE VOLTOOID!
# ==============================================================
# TRANSCRIPT PREVIEW (eerste 100 woorden)
# ==============================================================
# Hallo dit is een test video waar ik iets ga vertellen...
# ==============================================================
# TRANSCRIPT BEWERKEN (OPTIONEEL)
# ==============================================================
# ❓ Wil je het transcript bewerken? (j/n): j
#
# Openen van interview_timestamps.json in editor...
# 💡 Bewerk het bestand en sla het op in je editor
#    Druk op ENTER als je klaar bent om de video te genereren...

# [Je bewerkt het JSON bestand]
# [Druk ENTER]

# VIDEO GENEREREN
# ==============================================================
# Video generated successfully!
# ==============================================================
# ✓ SUCCES!
# ==============================================================
# Video met ondertitels: interview_styled.mp4
```

### Snelle Regeneratie (Timestamps Reuse!)

```bash
# Run 2: Andere kleur proberen (~30 seconden!)
python generate_with_style.py interview.mov --color cyan -o interview_cyan.mp4

# Script output:
# ✓ Found existing timestamps file: interview_timestamps.json
#    Skipping transcription and reusing existing timestamps...
#
# [Transcript preview]
# ❓ Wil je het transcript bewerken? (j/n): n
#
# VIDEO GENEREREN
# ==============================================================
# [Snel klaar!]
```

**Tijdsbesparing:**
- Eerste run: ~5-10 minuten (transcriptie)
- Elke volgende run: ~30 seconden (hergebruikt timestamps)

## 🎛️ Advanced Customization

### Volledige Style Aanpassingen

```bash
python generate_with_style.py video.mov \
  --color yellow \
  --stroke-width 4 \
  --outline-width 5 \
  --shadow-offset 8 \
  --fontsize 100 \
  --max-words 3 \
  --max-duration 2.0
```

**Beschikbare Opties:**
- `--color` - Highlight kleur (orange, cyan, yellow, red, lime, of hex code)
- `--stroke-width` - Binnenste stroke breedte [default: 3]
- `--outline-width` - Buitenste outline breedte (8-richtingen) [default: 4]
- `--no-outline` - Schakel outline uit
- `--shadow-offset` - Shadow offset in pixels [default: 6]
- `--no-shadow` - Schakel shadow uit
- `--fontsize` - Font grootte (auto-aangepast standaard)
- `--font` - Pad naar custom font bestand
- `--max-words` - Max woorden per regel [default: 4]
- `--max-duration` - Max duur per regel in seconden [default: 3.0]
- `-o, --output` - Custom output pad

### Experimenteren met Stijlen

```bash
# Subtiele stijl (dunne outline)
python generate_with_style.py video.mov \
  --stroke-width 2 \
  --outline-width 2 \
  --shadow-offset 4

# Dramatische stijl (dikke outline)
python generate_with_style.py video.mov \
  --stroke-width 5 \
  --outline-width 8 \
  --shadow-offset 10

# Zonder shadow/outline
python generate_with_style.py video.mov \
  --no-shadow \
  --no-outline
```

## 📝 Transcript Editing

Het script **pauzeert ALTIJD** na transcriptie om je te laten bewerken:

### Wat kun je bewerken?
- ✏️ Spelfouten corrigeren
- ✏️ Namen/bedrijfsnamen aanpassen
- ✏️ Hoofdletters verbeteren
- ✏️ Verkeerd gehoorde woorden fixen

### Editing Flow

```bash
python generate_with_style.py video.mov

# Script vraagt:
# ❓ Wil je het transcript bewerken? (j/n):

# Optie 1: Ja - bewerken
# j [ENTER]
# → Script opent JSON in TextEdit/Notepad
# → Je bewerkt en slaat op
# → Druk ENTER om door te gaan

# Optie 2: Nee - overslaan
# n [ENTER]
# → Direct naar video generatie
```

### JSON Structuur

```json
[
  {"word": " Hallo", "start": 0.0, "end": 0.5},
  {"word": " dit", "start": 0.5, "end": 0.8},
  {"word": " is", "start": 0.8, "end": 1.0}
]
```

## 🔄 Timestamps Hergebruik

### Automatische Detectie

Het script maakt deze bestanden:
```
video.mov
├── video_audio.mp3          # Audio (bewaard voor reuse)
├── video_timestamps.json    # Timestamps (bewaard voor reuse!)
└── video_styled.mp4         # Output video
```

Bij de tweede run:
```bash
python generate_with_style.py video.mov --color cyan

# Output:
# ✓ Found existing timestamps file: video_timestamps.json
#    Skipping transcription and reusing existing timestamps...
```

### Force Re-transcribe

Als je opnieuw wilt transcriberen (verkeerde tekst, andere taal, etc.):
```bash
rm video_timestamps.json
python generate_with_style.py video.mov
```

## 📱 iPhone/Mobile Videos

Perfect voor videos van je telefoon:

```bash
# iPhone video (.mov)
python generate_with_style.py IMG_1234.mov --color cyan

# Output automatisch correct formaat:
# - Portrait (1080x1920)? → Output ook 1080x1920
# - Landscape (1920x1080)? → Output ook 1920x1080
# - Font size aangepast aan resolutie
```

## 💡 Handige Tips

### 1. Verschillende kleuren proberen (snel!)
```bash
# Eerste run: transcribeer (langzaam)
python generate_with_style.py video.mov --color orange

# Probeer andere kleuren (snel - hergebruikt timestamps!)
python generate_with_style.py video.mov --color cyan -o video_cyan.mp4
python generate_with_style.py video.mov --color yellow -o video_yellow.mp4
python generate_with_style.py video.mov --color lime -o video_lime.mp4
```

### 2. Backup maken
```bash
# Voordat je JSON bewerkt
cp video_timestamps.json video_timestamps.json.backup
```

### 3. Preview transcript zonder video te maken
```bash
# Gebruik edit_and_generate.py voor preview only
python edit_and_generate.py --preview video_timestamps.json
```

## 🔧 Alternatieve Workflows

### Basis Workflow (Simpele Style)
Als je de enhanced styling niet nodig hebt:
```bash
python generate_subtitles.py video.mov
```

### Manual Two-Step Workflow
Meer controle over het proces:
```bash
# Stap 1: Transcribeer
python edit_and_generate.py video.mov

# Stap 2: Bewerk JSON handmatig

# Stap 3: Genereer video
python edit_and_generate.py --step2 video_timestamps.json video_audio.mp3
```

## ⚠️ Troubleshooting

### "ImageMagick not found"
```bash
# macOS
brew install imagemagick

# Ubuntu/Debian
sudo apt-get install imagemagick
```

### "FFmpeg not found"
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg
```

### JSON syntax error na bewerken
Valideer je JSON:
```bash
python -m json.tool video_timestamps.json
```

### Video wordt niet gegenereerd
Check of alle dependencies geïnstalleerd zijn:
```bash
pip install -r requirements.txt
```

## 📚 Meer Informatie

- [README.md](README.md) - Volledige documentatie
- [EDIT_WORKFLOW.md](EDIT_WORKFLOW.md) - Gedetailleerde edit instructies
- [generate_with_style.py](generate_with_style.py) - Source code met alle opties

## 🎯 Real World Voorbeeld: Frits.mov

Je hebt al een video verwerkt en de files bestaan:

```bash
# Bestanden aanwezig:
Frits_audio.mp3          # 732KB
Frits_timestamps.json    # 4.7KB (72 woorden)

# Snel nieuwe versie maken met andere kleur:
python generate_with_style.py \
  "/Users/joopsnijder/Library/Mobile Documents/com~apple~CloudDocs/Boek/Promotie/Frits.mov" \
  --color cyan \
  -o Frits_cyan.mp4

# Output:
# ✓ Found existing timestamps file: Frits_timestamps.json
#    Skipping transcription and reusing existing timestamps...
# Adjusted font size to 97 for 1080x1920 video
#
# [Preview transcript]
# ❓ Wil je het transcript bewerken? (j/n): n
#
# VIDEO GENEREREN
# ==============================================================
# Video generated successfully!
# ✓ SUCCES!
# Video met ondertitels: Frits_cyan.mp4
```

**Klaar in ~30 seconden!** 🚀
