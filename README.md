# sarvam-build

A voice-only web app that teaches **Odia to Hindi speakers** through role-play scenes, built on [Sarvam AI](https://docs.sarvam.ai). Made for a hackathon: small, credit-conscious, not production grade.

The tutor opens a scene ("हम एक कपड़ों की दुकान में हैं"), speaks the first line in Odia as a character, and you answer by voice in Hindi or Odia. It gives short Hindi feedback, suggests an Odia reply, and keeps a list of the words you've met.

## How it works

```
mic ──► browser (records, converts to 16 kHz WAV) ──► POST /api/turn
                                                          │
        Sarvam STT  (saaras:v3, language auto-detect) ◄───┤
        Sarvam LLM  (sarvam-105b, JSON reply)         ◄───┤
        Sarvam TTS  (bulbul:v3, od-IN, speaker "shubh") ◄─┘
                                                          │
browser ◄── scene + Hindi feedback + Odia line + hint + audio
```

- **Scenes** (`SCENARIOS` in `app.py`): shopping mall, restaurant, railway station, vegetable market. Add one by adding an entry there.
- **Start of a scene** (`POST /api/start`): 1 LLM call + 1 TTS call. The Hindi scene sentence and feedback are spoken free by the browser's `speechSynthesis` (`hi-IN`); only the Odia line uses Sarvam TTS.
- **Each turn** (`POST /api/turn`): 1 STT + 1 LLM + 1 TTS call.
- **UI states** of the glowing orb: idle (breathing), listening (red, pulses with mic level), thinking (amber spinner), speaking (green, pulses with playback level).
- **Tracking**: the sidebar shows words learned (`new_words` from the LLM, de-duplicated), API calls used vs. the cap, and the turn count. State is in memory only; restarting the server clears it.

## Requirements

- Python 3.12+
- A Sarvam API key with credits ([dashboard.sarvam.ai](https://dashboard.sarvam.ai/key-management))
- A browser with microphone access (Chrome/Firefox; `localhost` counts as a secure context)

## Setup

```bash
# .env in the project root
SARVAM_API_KEY=sk_...
# optional: hard cap on Sarvam API calls per server run (default 40)
MAX_API_CALLS=40
```

Install dependencies (`aiohttp`, `python-dotenv`) into your venv, then run:

```bash
PYTHONPATH=src .venv/bin/python -c "import sarvam_build; sarvam_build.main()"
```

Open http://localhost:8000, pick a scene, then tap the orb (or press Space) to start recording and tap again to send.

## API

| Route | Method | Body | Returns |
|---|---|---|---|
| `/` | GET | | the web page |
| `/api/state` | GET | | call counts, vocab, turn log, scenario list |
| `/api/start` | POST | `{"scenario": "mall"}` | opening scene, Odia line, hint, base64 WAV |
| `/api/turn` | POST | multipart `audio` (16 kHz mono WAV) | transcript, detected language, reply, base64 WAV |

Reply JSON fields: `scene`, `hindi` (feedback), `odia`, `roman`, `meaning`, `hint_odia`, `hint_roman`, `hint_meaning`, `new_words`.

## Credit usage

The server refuses requests once `MAX_API_CALLS` is reached. Notes learned while building:

- `sarvam-105b` is a reasoning model. With a small `max_tokens` it can spend the whole budget on reasoning and return empty text. The app uses `reasoning_effort: "low"` and `max_tokens: 4000`, which costs more tokens per call and makes scene starts slow.
- `bulbul:v4-flash` has no Odia voices, so TTS uses `bulbul:v3`.
- If the model's reply can't be parsed as JSON, the server logs the raw text and returns an empty reply for that turn.

## Sarvam MCP (optional, for the coding agent)

The Sarvam MCP server (`uvx sarvam-mcp`) can be registered in `.omp/agent/mcp.json` with `SARVAM_API_KEY` in its `env`. That file is git-ignored because it holds the key. The app itself does not use MCP; it calls the Sarvam REST API directly.

## Project layout

```
src/sarvam_build/
  __init__.py   exports main()
  app.py        aiohttp server, Sarvam STT/LLM/TTS calls, scenarios, state
  index.html    single-page UI (orb, recorder, WAV encoder, scene picker)
```

`.env`, `.omp/`, `guide.md`, `prompt.md` and `.venv/` are git-ignored.

## Known limits

- Single global session: one learner at a time, no persistence.
- Recording is tap-to-start / tap-to-stop (no silence detection).
- Replies are only as good as the LLM's Odia; check unfamiliar phrases before relying on them.
