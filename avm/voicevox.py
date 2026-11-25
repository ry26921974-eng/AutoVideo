"""VOICEVOX エンジン（http://127.0.0.1:50021）との連携。"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request


class VoicevoxError(RuntimeError):
    pass


class Voicevox:
    def __init__(self, url: str = "http://127.0.0.1:50021", timeout: float = 60):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _req(self, method: str, path: str, params: dict | None = None, body: bytes | None = None) -> bytes:
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(self.url + path + q, data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except OSError as e:
            raise VoicevoxError(
                f"VOICEVOX に接続できません（{self.url}）。VOICEVOX を起動してから、もう一度お試しください。\n{e}"
            ) from e

    def is_alive(self) -> bool:
        try:
            self._req("GET", "/version")
            return True
        except VoicevoxError:
            return False

    def speakers(self) -> list[tuple[str, int]]:
        """[(\"ずんだもん（ノーマル）\", 3), ...]"""
        data = json.loads(self._req("GET", "/speakers"))
        out = []
        for sp in data:
            for st in sp.get("styles", []):
                out.append((f"{sp['name']}（{st['name']}）", int(st["id"])))
        return out

    def synthesize(self, text: str, speaker: int, speed: float = 1.0) -> bytes:
        q = json.loads(self._req("POST", "/audio_query", {"text": text, "speaker": speaker}))
        q["speedScale"] = speed
        q["outputSamplingRate"] = 48000
        q["outputStereo"] = True
        return self._req("POST", "/synthesis", {"speaker": speaker}, json.dumps(q).encode("utf-8"))

    def synthesize_cached(self, text: str, speaker: int, speed: float, cache_dir: str) -> str:
        os.makedirs(cache_dir, exist_ok=True)
        h = hashlib.sha1(f"{speaker}|{speed}|{text}".encode("utf-8")).hexdigest()[:16]
        path = os.path.join(cache_dir, f"{h}.wav")
        if not os.path.exists(path):
            data = self.synthesize(text, speaker, speed)
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
        return path
