"""Клиенты LLM: GigaChat, любой OpenAI-совместимый API (OpenRouter) и дисковый кэш ответов.

Ключи берутся из переменных окружения или файла .env в корне проекта (см. .env.example).
"""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


class LLMError(Exception):
    pass


def load_env(path=ROOT / ".env"):
    """Минимальный разбор .env: KEY=VALUE, без перезаписи уже заданных переменных."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _post(url, retries=3, **kw):
    for attempt in range(retries):
        try:
            r = httpx.post(url, **kw)
        except httpx.HTTPError as e:
            err = e
        else:
            if r.status_code < 400:
                return r.json()
            err = LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        time.sleep(2 ** attempt * 2)
    raise LLMError(str(err))


class GigaChat:
    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    name = "gigachat"

    def __init__(self, credentials, model="GigaChat-2-Max", scope="GIGACHAT_API_PERS", verify=True, timeout=90):
        self.credentials, self.model, self.scope = credentials, model, scope
        # Сертификаты GigaChat выпущены российским УЦ: путь к ним — GIGACHAT_CA_BUNDLE, либо проверку можно отключить.
        self.verify, self.timeout = verify, timeout
        self._token, self._expires = None, 0.0

    def _auth(self):
        if self._token and time.time() < self._expires - 60:
            return self._token
        j = _post(self.OAUTH_URL, data={"scope": self.scope}, verify=self.verify, timeout=self.timeout,
                  headers={"Authorization": f"Basic {self.credentials}", "RqUID": str(uuid.uuid4()),
                           "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        self._token, self._expires = j["access_token"], j["expires_at"] / 1000
        return self._token

    def chat(self, messages, temperature):
        j = _post(self.CHAT_URL, verify=self.verify, timeout=self.timeout,
                  headers={"Authorization": f"Bearer {self._auth()}"},
                  json={"model": self.model, "messages": messages, "max_tokens": 2500,
                        "temperature": max(temperature, 0.01)})  # GigaChat не принимает temperature = 0
        return j["choices"][0]["message"]["content"]


class OpenAICompatible:
    def __init__(self, base_url, api_key, model, name="openai-compatible", timeout=120):
        self.base_url, self.api_key, self.model, self.name, self.timeout = base_url.rstrip("/"), api_key, model, name, timeout

    def chat(self, messages, temperature):
        j = _post(f"{self.base_url}/chat/completions", timeout=self.timeout,
                  headers={"Authorization": f"Bearer {self.api_key}"},
                  json={"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": 2500})
        if "choices" not in j:
            raise LLMError(f"Нет ответа модели: {str(j)[:300]}")
        return j["choices"][0]["message"]["content"]


class Chain:
    """Пробует провайдеров по очереди: основной, затем запасные."""

    def __init__(self, providers):
        self.providers = providers
        self.name = "+".join(p.name for p in providers)
        self.model = "+".join(p.model for p in providers)
        self.last_used = None

    def chat(self, messages, temperature):
        errors = []
        for p in self.providers:
            try:
                out = p.chat(messages, temperature)
                self.last_used = f"{p.name}:{p.model}"
                return out
            except LLMError as e:
                errors.append(f"{p.name}: {e}")
        raise LLMError("; ".join(errors))


class Cached:
    """Кэш на диске: повторный прогон тех же анкет с тем же промптом не тратит токены."""

    def __init__(self, inner, cache_dir=ROOT / "data" / "llm_cache"):
        self.inner, self.dir = inner, Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.name, self.model = inner.name, inner.model
        self.hits = self.calls = 0

    def chat(self, messages, temperature, run=0):
        key = hashlib.sha256(json.dumps([self.name, self.model, temperature, run, messages],
                                        ensure_ascii=False).encode()).hexdigest()[:24]
        path = self.dir / f"{key}.json"
        if path.exists():
            self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["content"]
        self.calls += 1
        content = self.inner.chat(messages, temperature)
        path.write_text(json.dumps({"model": getattr(self.inner, "last_used", None) or f"{self.name}:{self.model}",
                                    "content": content}, ensure_ascii=False), encoding="utf-8")
        return content


def make_provider(name="auto"):
    """gigachat | openrouter | auto (GigaChat с запасным OpenRouter — какие ключи заданы)."""
    load_env()
    providers = []
    if name in ("gigachat", "auto") and os.environ.get("GIGACHAT_CREDENTIALS"):
        verify = os.environ.get("GIGACHAT_CA_BUNDLE") or os.environ.get("GIGACHAT_VERIFY_SSL", "true").lower() != "false"
        providers.append(GigaChat(os.environ["GIGACHAT_CREDENTIALS"], os.environ.get("GIGACHAT_MODEL", "GigaChat-2-Max"),
                                  os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"), verify))
    if name in ("openrouter", "auto") and os.environ.get("OPENROUTER_API_KEY"):
        providers.append(OpenAICompatible("https://openrouter.ai/api/v1", os.environ["OPENROUTER_API_KEY"],
                                          os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-235b-a22b:free"), "openrouter"))
    if not providers:
        raise LLMError(f"Для провайдера «{name}» не заданы ключи: заполните .env по образцу .env.example")
    return Cached(providers[0] if len(providers) == 1 else Chain(providers))
