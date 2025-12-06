# Transcript Bewerken Workflow

Deze workflow laat je de transcript controleren en aanpassen voordat de video gegenereerd wordt.

## Waarom Gebruiken?

Whisper is heel accuraat, maar maakt soms fouten:
- Namen worden verkeerd gespeld
- Technische termen worden niet herkend
- Interpunctie kan verbeterd worden
- Nederlandse woorden kunnen verkeerd geïnterpreteerd worden

## Twee-Stappen Workflow

### Stap 1: Transcribeer Video

```bash
python edit_and_generate.py video.mov
```

Dit doet:
1. ✅ Extraheert audio
2. ✅ Transcribeert met Whisper
3. ✅ Slaat word timestamps op in JSON
4. ✅ Toont preview van de transcript

**Output:**
- `video_timestamps.json` - Bewerkbaar transcript bestand
- `video_audio.mp3` - Audio bestand (nodig voor stap 2)

### Stap 2: Bewerk de Transcript

Open `video_timestamps.json` in een text editor. Het ziet er zo uit:

```json
[
  {
    "word": " Hallo",
    "start": 0.5,
    "end": 0.8
  },
  {
    "word": " wereld",
    "start": 0.8,
    "end": 1.2
  }
]
```

**Wat Je Kan Aanpassen:**
- `"word"`: De tekst (pas spelling/interpunctie aan)
- `"start"` en `"end"`: Timing (meestal niet nodig)

**Tips:**
- Behoud de spatie vóór woorden (bijv. `" Hallo"` niet `"Hallo"`)
- Gebruik een JSON validator als je onzeker bent
- Maak een backup voordat je grote wijzigingen maakt

### Stap 3: Genereer Video met Aangepaste Transcript

```bash
python edit_and_generate.py --step2 video_timestamps.json video_audio.mp3
```

Dit genereert de video met jouw aangepaste tekst!

**Optioneel: Custom output naam:**
```bash
python edit_and_generate.py --step2 video_timestamps.json video_audio.mp3 -o final.mp4
```

## Extra Commando's

### Preview Transcript

Bekijk de transcript zonder video te genereren:

```bash
python edit_and_generate.py --preview video_timestamps.json
```

### Verschillende Whisper Models

Voor betere transcriptie kwaliteit:

```bash
# Snel (minder accuraat)
python edit_and_generate.py video.mov --model tiny

# Balans (default)
python edit_and_generate.py video.mov --model medium

# Beste kwaliteit (langzaam)
python edit_and_generate.py video.mov --model large
```

## Complete Voorbeeld

```bash
# Stap 1: Transcribeer
python edit_and_generate.py '/Users/joopsnijder/Videos/Frits.mov' --model medium

# Output toont:
# - Timestamps saved to: /Users/joopsnijder/Videos/Frits_timestamps.json
# - Audio saved to: /Users/joopsnijder/Videos/Frits_audio.mp3
# - Preview van eerste 100 woorden

# Stap 2: Bewerk JSON bestand
# Open Frits_timestamps.json in je editor en pas fouten aan

# Stap 3: Genereer video
python edit_and_generate.py --step2 \
  '/Users/joopsnijder/Videos/Frits_timestamps.json' \
  '/Users/joopsnijder/Videos/Frits_audio.mp3' \
  -o '/Users/joopsnijder/Videos/Frits_final.mp4'
```

## Veelgemaakte Fouten Corrigeren

### Namen
```json
// Voor:
{"word": " Jan", ...}

// Na:
{"word": " John", ...}
```

### Hoofdletters
```json
// Voor:
{"word": " amsterdam", ...}

// Na:
{"word": " Amsterdam", ...}
```

### Getallen
```json
// Voor:
{"word": " vijftig", ...}

// Na:
{"word": " 50", ...}
```

### Meerdere Woorden Samenvoegen

Als je twee woorden wilt samenvoegen:

```json
// Voor:
{"word": " video", "start": 1.0, "end": 1.3},
{"word": " conferentie", "start": 1.3, "end": 1.8}

// Na (verwijder 2e entry en voeg samen):
{"word": " videoconferentie", "start": 1.0, "end": 1.8}
```

## Troubleshooting

### JSON Syntax Error

Als je een fout krijgt bij stap 2:

```bash
# Check of JSON geldig is
python -m json.tool video_timestamps.json
```

### Woorden Missen

Als woorden verdwijnen in de video:
- Check of je niet per ongeluk entries hebt verwijderd
- Zorg dat de timestamps logisch zijn (start < end)

### Video Genereert Niet

Eerst ImageMagick installeren (als je dat nog niet gedaan hebt):

```bash
brew install imagemagick
```

## Vergelijking met Directe Workflow

### Direct (zonder bewerken):
```bash
python generate_subtitles.py video.mov
```
- ✅ Snel
- ❌ Geen controle over tekst

### Met Bewerken:
```bash
# Stap 1
python edit_and_generate.py video.mov

# Bewerk JSON...

# Stap 2
python edit_and_generate.py --step2 video_timestamps.json video_audio.mp3
```
- ✅ Volledige controle over tekst
- ✅ Corrigeer fouten vooraf
- ✅ Perfecte output
- ⏱️ Iets langzamer (door handmatige stap)

## Tips voor Beste Resultaten

1. **Gebruik medium of large model** voor betere transcriptie
2. **Check de preview** na stap 1 voor veel fouten
3. **Maak een backup** van de JSON voordat je bewerkt
4. **Test met korte clip** eerst om workflow te leren
5. **Gebruik find/replace** in editor voor bulk wijzigingen

## Volgende Stappen

Na het genereren van de video, bekijk:
- [README.md](README.md) - Volledige documentatie
- [generate_subtitles.py](generate_subtitles.py) - Direct workflow
- [example_usage.py](example_usage.py) - Programmatisch gebruik
