from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Any

from pypresence import AioPresence, ActivityType
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as MediaPlaybackStatus,
)


APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "YandexMusicDiscordRPC"
CONFIG_PATH = APP_DIR / "config.json"
POLL_SECONDS = 5


def load_config() -> dict[str, Any]:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            print(f"Не удалось прочитать настройки: {CONFIG_PATH}")

    print("Первый запуск — настройка Discord Rich Presence")
    print("Создай приложение на https://discord.com/developers/applications")
    app_id = input("Вставь Application ID (General Information → Application ID): ").strip()
    if not app_id.isdigit():
        raise SystemExit("Нужен числовой Application ID. Запусти start.bat ещё раз.")

    config = {"discord_application_id": app_id, "source_hint": "yandex"}
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Настройки сохранены: {CONFIG_PATH}")
    return config


def session_source(session: Any) -> str:
    try:
        return str(session.source_app_user_model_id or "")
    except Exception:
        return ""


async def get_yandex_track(manager: Any, source_hint: str) -> dict[str, Any] | None:
    sessions = list(manager.get_sessions())
    hint = source_hint.casefold()
    session = next((s for s in sessions if hint in session_source(s).casefold()), None)
    if session is None:
        return None

    info = session.get_playback_info()
    if info.playback_status not in (MediaPlaybackStatus.PLAYING, MediaPlaybackStatus.PAUSED):
        return None

    media = await session.try_get_media_properties_async()
    title = (media.title or "").strip()
    artist = (media.artist or "").strip()
    if not title:
        return None

    track: dict[str, Any] = {
        "title": title[:128],
        "artist": (artist or "Яндекс Музыка")[:128],
        "playing": info.playback_status == MediaPlaybackStatus.PLAYING,
    }
    if track["playing"]:
        timeline = session.get_timeline_properties()
        start = getattr(timeline, "start_time", None)
        end = getattr(timeline, "end_time", None)
        if start and end and end > start:
            remaining = (end - timeline.position).total_seconds()
            if 0 < remaining < 24 * 60 * 60:
                now = int(time.time())
                track["start"] = now - max(0, int(timeline.position.total_seconds()))
                track["end"] = now + int(remaining)
    return track


async def run() -> None:
    config = load_config()
    app_id = str(config.get("discord_application_id", "")).strip()
    source_hint = str(config.get("source_hint", "yandex")).strip() or "yandex"
    if not app_id.isdigit():
        raise SystemExit("Проверь discord_application_id в настройках: нужен числовой Application ID.")

    manager = await SessionManager.request_async()
    rpc: AioPresence | None = None
    last_key: tuple[Any, ...] | None = None
    stop_requested = asyncio.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_requested.set())
    print("Ищу Яндекс Музыку. Оставь это окно открытым; выход — Ctrl+C.")

    while not stop_requested.is_set():
        try:
            track = await get_yandex_track(manager, source_hint)
            if track is None:
                if rpc is not None and last_key is not None:
                    try:
                        await rpc.clear()
                    except Exception:
                        rpc = None
                last_key = None
                await asyncio.sleep(POLL_SECONDS)
                continue

            key = (track["title"], track["artist"], track["playing"])
            if rpc is None:
                rpc = AioPresence(app_id)
                await rpc.connect()
                print("Подключено к Discord RPC.")

            if key != last_key:
                payload: dict[str, Any] = {
                    "details": track["title"],
                    "state": f"Исполнитель: {track['artist']}" if track["playing"] else f"На паузе · {track['artist']}",
                    "activity_type": ActivityType.LISTENING,
                    "large_image": "yandex_music_rpc_icon",
                    "large_text": "Яндекс Музыка",
                }
                if track["playing"] and "start" in track and "end" in track:
                    payload.update(start=track["start"], end=track["end"])
                await rpc.update(**payload)
                last_key = key
                print(f"{'▶' if track['playing'] else '⏸'} {track['artist']} — {track['title']}")
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"Ошибка: {exc}. Повторное подключение через {POLL_SECONDS} сек.")
            if rpc is not None:
                try:
                    writer = rpc.sock_writer
                    if writer is not None:
                        writer.close()
                except Exception:
                    pass
                rpc = None
            last_key = None

        await asyncio.sleep(POLL_SECONDS)

    if rpc is not None:
        try:
            await rpc.clear()
            writer = rpc.sock_writer
            if writer is not None:
                writer.close()
        except Exception:
            pass
    print("RPC остановлен.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run())
