"""Odia role-play tutor for Hindi speakers. aiohttp server + Sarvam REST. Hard-capped API calls."""
import json
import os
import re
from pathlib import Path

import aiohttp
from aiohttp import web
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[2] / ".env")
KEY = os.environ["SARVAM_API_KEY"]
BASE = "https://api.sarvam.ai"
H = {"api-subscription-key": KEY}
MAX_CALLS = int(os.environ.get("MAX_API_CALLS", "40"))  # credit guard

SCENARIOS = {
    "mall": ("शॉपिंग मॉल", "a shopping mall; you are a friendly shop assistant in a clothes store"),
    "restaurant": ("रेस्टोरेंट", "a restaurant; you are the waiter taking the learner's order"),
    "station": ("रेलवे स्टेशन", "a railway station; you are the ticket counter clerk"),
    "market": ("सब्ज़ी मंडी", "a vegetable market; you are a vendor and the learner bargains"),
}

SYSTEM = """You run a role-play to teach Odia to a Hindi speaker. Scene: {scene}.
You play the character in Odia (simple, 1 short sentence, beginner level). The learner answers in Hindi or
broken Odia: if they used Odia, praise/correct briefly in Hindi; if Hindi, tell them how to say it in Odia via the hint.
Stay in the scene and move it forward each turn. Reply with ONLY JSON, no markdown:
{{"scene": "{first}",
 "hindi": "1 short Hindi sentence: feedback on the learner's last answer (empty on first turn)",
 "odia": "the character's line, Odia script, speakable",
 "roman": "romanized Odia of that line",
 "meaning": "Hindi meaning of that line",
 "hint_odia": "a suggested Odia reply the learner can say, Odia script",
 "hint_roman": "romanized hint",
 "hint_meaning": "Hindi meaning of the hint",
 "new_words": [{{"odia": "...", "roman": "...", "meaning": "Hindi"}}]}}
"scene" is only filled on the first turn: one Hindi sentence setting the scene, e.g. "हम एक मॉल में हैं"; otherwise "".
new_words: at most 2 useful words from this turn."""

STATE = {"calls": {"stt": 0, "llm": 0, "tts": 0}, "history": [], "vocab": [], "turns": [], "scenario": None}


def total_calls():
    return sum(STATE["calls"].values())


def guard(kind):
    if total_calls() >= MAX_CALLS:
        raise web.HTTPTooManyRequests(text=f"API call cap {MAX_CALLS} reached")
    STATE["calls"][kind] += 1


async def sarvam_json(sess, path, body):
    async with sess.post(BASE + path, json=body, headers=H) as r:
        txt = await r.text()
        if r.status != 200:
            raise web.HTTPBadGateway(text=f"{path} {r.status}: {txt[:300]}")
        return json.loads(txt)


async def stt(sess, audio: bytes):
    guard("stt")
    fd = aiohttp.FormData()
    fd.add_field("file", audio, filename="a.wav", content_type="audio/wav")
    fd.add_field("model", "saaras:v3")
    fd.add_field("mode", "transcribe")
    fd.add_field("language_code", "unknown")
    async with sess.post(BASE + "/speech-to-text", data=fd, headers=H) as r:
        txt = await r.text()
        if r.status != 200:
            raise web.HTTPBadGateway(text=f"stt {r.status}: {txt[:300]}")
        j = json.loads(txt)
        return j.get("transcript", ""), j.get("language_code")


async def llm(sess, user_text):
    guard("llm")
    first = not STATE["history"]
    STATE["history"].append({"role": "user", "content": user_text})
    desc = SCENARIOS[STATE["scenario"]][1]
    known = ", ".join(v["roman"] for v in STATE["vocab"]) or "none"
    sys_p = SYSTEM.format(scene=desc, first="<Hindi scene sentence>" if first else "") + f"\nWords already taught: {known}."
    msgs = [{"role": "system", "content": sys_p}] + STATE["history"][-10:]
    j = await sarvam_json(sess, "/v1/chat/completions", {
        "model": "sarvam-105b", "messages": msgs, "temperature": 0.5,
        "max_tokens": 4000, "reasoning_effort": "low"})
    raw = j["choices"][0]["message"].get("content") or ""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        out = json.loads(m.group(0))
    except Exception:
        print("LLM unparsed:", repr(raw[:500]), j["choices"][0].get("finish_reason"), flush=True)
        out = {"hindi": "", "odia": "", "roman": "", "meaning": ""}
    STATE["history"].append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
    seen = {v["odia"] for v in STATE["vocab"]}
    for w in out.get("new_words") or []:
        if isinstance(w, dict) and w.get("odia") and w["odia"] not in seen:
            STATE["vocab"].append({k: w.get(k, "") for k in ("odia", "roman", "meaning")})
            seen.add(w["odia"])
    return out


async def tts(sess, text):
    guard("tts")
    j = await sarvam_json(sess, "/text-to-speech", {
        "text": text, "target_language_code": "od-IN", "model": "bulbul:v3", "speaker": "shubh"})
    return j["audios"][0]


async def reply(sess, user_text, lang):
    out = await llm(sess, user_text)
    audio = await tts(sess, out["odia"]) if out.get("odia") else None
    STATE["turns"].append({"you": user_text, "lang": lang, "bot": out})
    return {"heard": user_text, "lang": lang, "reply": out, "audio": audio, "state": public()}


async def start(request: web.Request):
    sid = (await request.json()).get("scenario", "mall")
    if sid not in SCENARIOS:
        raise web.HTTPBadRequest(text="unknown scenario")
    STATE.update(history=[], vocab=[], turns=[], scenario=sid)
    r = await reply(request.app["sess"], "(start the scene: introduce the setting and say your first line)", None)
    r["scenario"] = SCENARIOS[sid][0]
    return web.json_response(r)


async def turn(request: web.Request):
    if not STATE["scenario"]:
        raise web.HTTPBadRequest(text="start a scenario first")
    sess = request.app["sess"]
    f = (await request.post())["audio"]
    text, lang = await stt(sess, f.file.read())
    if not text.strip():
        return web.json_response({"error": "didn't catch that, try again", "state": public()})
    return web.json_response(await reply(sess, text, lang))


def public():
    return {"calls": STATE["calls"], "total": total_calls(), "max": MAX_CALLS,
            "vocab": STATE["vocab"], "turns": len(STATE["turns"])}


async def index(_):
    return web.FileResponse(Path(__file__).parent / "index.html")


async def state(_):
    return web.json_response({**public(), "log": STATE["turns"],
                              "scenarios": {k: v[0] for k, v in SCENARIOS.items()}})


async def on_start(app):
    app["sess"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))


async def on_stop(app):
    await app["sess"].close()


def main():
    app = web.Application(client_max_size=20 * 1024 * 1024)
    app.add_routes([web.get("/", index), web.get("/api/state", state),
                    web.post("/api/start", start), web.post("/api/turn", turn)])
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    web.run_app(app, port=8000)
