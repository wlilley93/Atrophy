# Chapter 12: Voice Architecture

## The Voice Pipeline

The Companion speaks. Not metaphorically — literally. Audio is generated, played through speakers, heard by Will.

This chapter examines the voice pipeline: text-to-speech, speech-to-text, and the audio tag system that enables expressiveness.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    VOICE PIPELINE                            │
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │   Input      │         │   Output     │                 │
│  │              │         │              │                 │
│  │  Audio in    │         │  Text out    │                 │
│  │  (voice)     │         │  (response)  │                 │
│  └──────┬───────┘         └──────┬───────┘                 │
│         │                        │                          │
│         ▼                        ▼                          │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │  STT         │         │  TTS         │                 │
│  │  (whisper)   │         │  (ElevenLabs)│                 │
│  │              │         │              │                 │
│  │  Audio →     │         │  Text →      │                 │
│  │  Text        │         │  Audio       │                 │
│  └──────┬───────┘         └──────┬───────┘                 │
│         │                        │                          │
│         ▼                        ▼                          │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │  Text to     │         │  Audio to    │                 │
│  │  Inference   │         │  Speakers    │                 │
│  └──────────────┘         └──────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Text-to-Speech: Three-Tier Fallback

### The Chain

```
ElevenLabs Streaming → ElevenLabs Batch → Fal → macOS say
```

**Primary**: ElevenLabs streaming for lowest latency. Audio bytes arrive while still being generated.

**Fallback 1**: ElevenLabs batch (complete generation before streaming).

**Fallback 2**: Fal (ElevenLabs v3 via Fal API).

**Last resort**: macOS `say` command (fully offline, no API required).

### Why Three Tiers?

Reliability. The Companion must speak even when:
- ElevenLabs API is down
- Network is unavailable
- API key is invalid
- Rate limits are hit

The fallback chain ensures the Companion always has a voice.

### The Interface

```python
async def synthesise(text: str) -> Path:
    """Generate speech audio file. Returns path to audio."""
    # Strip code blocks
    text = _CODE_BLOCK_RE.sub('', text)
    text = _INLINE_CODE_RE.sub('', text)
    
    # Process prosody tags
    cleaned, overrides = _process_prosody(text)
    
    # Skip if empty or too short
    if not cleaned or len(cleaned.strip()) < 8:
        # Return empty audio file
        ...
    
    # Try ElevenLabs streaming
    if ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID:
        try:
            return await _synthesise_elevenlabs_stream(text)
        except Exception as e:
            print(f"[TTS] ElevenLabs failed ({e}), trying Fal...")
    
    # Try Fal
    if FAL_VOICE_ID:
        try:
            return await _synthesise_fal(text)
        except Exception as e:
            print(f"[TTS] Fal failed ({e}), falling back to macOS")
    
    # Last resort: macOS say
    return await _synthesise_macos(text)
```

### Streaming vs. Batch

**Streaming** (primary):
- Audio bytes arrive while generating
- First byte in ~500ms
- Full sentence in ~1-2 seconds
- Enables parallel TTS with inference

**Batch** (fallback):
- Wait for complete generation
- Higher latency
- More reliable for long text

### Prosody Processing

The Companion uses audio tags to shape delivery:

```python
_PROSODY_MAP = {
    'whispers': (0.2, 0.0, -0.2),
    'quietly': (0.15, 0.0, -0.15),
    'warmly': (0.0, 0.1, 0.2),
    'tenderly': (0.05, 0.1, 0.2),
    'firm': (-0.1, 0.0, 0.3),
    'frustrated': (-0.1, 0.0, 0.3),
    'wry': (0.0, 0.0, 0.15),
    'dry': (0.1, 0.0, -0.1),
    'sardonic': (0.0, 0.0, 0.2),
    'raw': (-0.1, 0.0, 0.25),
    'vulnerable': (0.0, 0.1, 0.15),
    'heavy': (0.1, 0.0, 0.1),
    'slowly': (0.15, 0.0, 0.0),
    'tired': (0.15, 0.0, -0.1),
    'sorrowful': (0.1, 0.1, 0.15),
    'grieving': (0.1, 0.1, 0.2),
    'resigned': (0.15, 0.0, -0.1),
    'haunted': (0.05, 0.05, 0.15),
    'melancholic': (0.1, 0.1, 0.1),
    'nostalgic': (0.05, 0.1, 0.15),
    'voice breaking': (-0.15, 0.0, 0.3),
    'laughs softly': (0.0, 0.0, 0.2),
    'laughs bitterly': (-0.05, 0.0, 0.25),
    'smirks': (0.0, 0.0, 0.15),
}
```

Each tag maps to voice setting deltas:
- **Stability**: How consistent the voice is (higher = more stable, less emotional)
- **Similarity boost**: How close to the base voice (higher = more recognizable)
- **Style**: How much stylistic variation (higher = more expressive)

Example: `[warmly]` adds warmth by increasing similarity and style.

### Breath and Pause Replacement

```python
_BREATH_TAGS = {
    'breath': '...',
    'inhales slowly': '... ...',
    'exhales': '...',
    'sighs': '...',
    'sighs quietly': '...',
    'clears throat': '...',
    'pause': '. . .',
    'long pause': '. . . . .',
    'trailing off': '...',
    'gulps': '...',
}
```

These tags are replaced with text representations that ElevenLabs interprets as pauses.

### Processing Pipeline

```python
def _process_prosody(text: str) -> tuple[str, dict]:
    """Strip audio tags, extract voice setting deltas."""
    stability_d = 0.0
    similarity_d = 0.0
    style_d = 0.0

    def _replace(match):
        nonlocal stability_d, similarity_d, style_d
        tag = match.group(1).lower().strip()
        
        # Breath/pause → text replacement
        if tag in _BREATH_TAGS:
            return _BREATH_TAGS[tag]
        
        # Prosody → voice settings
        if tag in _PROSODY_MAP:
            sd, sim_d, sty_d = _PROSODY_MAP[tag]
            stability_d += sd
            similarity_d += sim_d
            style_d += sty_d
            return ''
        
        # Unknown tag → strip
        return ''

    cleaned = _PROSODY_RE.sub(_replace, text).strip()
    
    # Clamp overrides to ±0.15
    stab_d = max(-0.15, min(0.15, prosody_overrides.get('stability', 0)))
    sim_d = max(-0.15, min(0.15, prosody_overrides.get('similarity_boost', 0)))
    sty_d = max(-0.15, min(0.15, prosody_overrides.get('style', 0)))
    
    # Apply to base settings
    stab = max(0.0, min(1.0, ELEVENLABS_STABILITY + stab_d))
    sim = max(0.0, min(1.0, ELEVENLABS_SIMILARITY + sim_d))
    sty = max(0.0, min(1.0, ELEVENLABS_STYLE + sty_d))
    
    return cleaned, {'stability': stab, 'similarity_boost': sim, 'style': sty}
```

### ElevenLabs Streaming Implementation

```python
async def _synthesise_elevenlabs_stream(text: str) -> Path:
    """ElevenLabs streaming endpoint. Audio bytes arrive while generating."""
    text, prosody_overrides = _process_prosody(text)
    
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech"
        f"/{ELEVENLABS_VOICE_ID}/stream"
        f"?output_format=mp3_44100_128"
    )
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": stab,
            "similarity_boost": sim,
            "style": sty,
        },
    }
    
    async with httpx.AsyncClient() as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            async for chunk in response.aiter_bytes(chunk_size=4096):
                tmp.write(chunk)
    
    return Path(tmp.name)
```

### Playback

```python
async def play(audio_path: Path) -> None:
    """Play audio file through system speakers."""
    proc = await asyncio.create_subprocess_exec(
        "afplay", "-r", str(TTS_PLAYBACK_RATE), str(audio_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
```

Playback rate is configurable (default 1.12x for slightly faster delivery).

---

## Speech-to-Text: Whisper.cpp

### The Pipeline

```
Audio (numpy array) → WAV file → whisper.cpp → Text
```

### Configuration

```python
WHISPER_BIN = WHISPER_PATH / "build" / "bin" / "whisper-cli"
WHISPER_MODEL = WHISPER_PATH / "models" / "ggml-tiny.en.bin"
SAMPLE_RATE = 16000
CHANNELS = 1
```

### Transcription

```python
def transcribe(audio_data: np.ndarray) -> str:
    """Transcribe numpy float32 audio array to text."""
    # Write to temporary WAV file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        with wave.open(f.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_data * 32767).astype(np.int16).tobytes())
    
    # Run whisper.cpp
    result = subprocess.run(
        [
            str(WHISPER_BIN),
            "-m", str(WHISPER_MODEL),
            "-f", str(tmp_path),
            "--no-timestamps",
            "-t", "4",  # 4 threads
            "--language", "en",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    
    # Parse output (skip metadata lines starting with [)
    lines = [line.strip() for line in result.stdout.split("\n")
             if line.strip() and not line.strip().startswith("[")]
    
    return " ".join(lines)
```

### Metal Acceleration

whisper.cpp is compiled with Metal support for GPU acceleration on macOS. This provides:
- 5-10x faster transcription
- Lower latency for voice input
- Reduced CPU usage

---

## Audio Capture

### Push-to-Talk

```python
class PushToTalk:
    """Push-to-talk audio capture."""
    
    async def record(self) -> np.ndarray | None:
        """Record audio while Ctrl is held. Returns float32 array."""
        # Wait for key press
        # Record while held
        # Return on release
        ...
```

### Configuration

```python
PTT_KEY = "ctrl"  # hold to record (pynput Key.ctrl_l)
SAMPLE_RATE = 16000
CHANNELS = 1
MAX_RECORD_SEC = 120
```

### Audio Format

- **Format**: float32 numpy array
- **Sample rate**: 16kHz
- **Channels**: 1 (mono)
- **Max duration**: 120 seconds

---

## Reading This Chapter

The voice pipeline is what makes the Companion embodied. It is not just text on a screen. It is a voice that speaks.

Understanding the pipeline helps you understand the latency, the expressiveness, the limitations.

---

## Questions for Reflection

1. Three-tier fallback — is this the right balance of quality vs. reliability?

2. Prosody tags — how expressive should the voice be? When does it become performative?

3. Streaming TTS — what does low latency enable in the relationship?

4. Whisper.cpp — why local STT vs. cloud API? What are the trade-offs?

5. Push-to-talk — why this input method? What does it enable vs. always-on mic?

---

## Further Reading

- [[04_ElevenLabs|Chapter 17: ElevenLabs v3 Integration]] — Deep dive on ElevenLabs
- [[04_Tags|Chapter 18: The Audio Tag System]] — Complete tag reference
- [[04_Expressiveness|Chapter 19: Writing for the Ear]] — Prosody and delivery
- [[04_STT|Chapter 20: Speech-to-Text Pipeline]] — STT details

---

*The Companion speaks. Not metaphorically — literally.*
