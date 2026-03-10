import sqlite3
import os
import pygame
import yt_dlp
import threading
import re
import time

pygame.init()

# ── Playback state ────────────────────────────────────────────────────────────
_current_id: int | None = None
_loop = False
_advance_thread: threading.Thread | None = None
_is_paused = False
_stop_watcher = False
_stop_event = threading.Event()

def _watch_and_advance():
    global _stop_watcher

    # Wait for song to actually start
    time.sleep(2.0)

    while not _stop_watcher:
        time.sleep(0.5)

        if _stop_watcher:
            break

        if not _is_paused and not pygame.mixer.music.get_busy():
            if _loop:
                pygame.mixer.music.play()
                # FIX 1: Check _stop_watcher after sleep so we don't zombie
                for _ in range(4):
                    if _stop_watcher:
                        break
                    time.sleep(0.5)
            else:
                # FIX 2: Don't reset _stop_watcher here — play_music will manage it
                _advance_to_next_internal()
                return

    _stop_watcher = False
    _stop_event.clear()


def _advance_to_next_internal():
    """Internal: advance to next song."""
    global _current_id

    if _current_id is None:
        return

    all_songs = get_all_music()
    if not all_songs:
        return

    ids = [s["id"] for s in all_songs]

    if _current_id in ids:
        idx = ids.index(_current_id)
        next_idx = (idx + 1) % len(ids)
    else:
        next_idx = 0

    play_music(ids[next_idx])


def _play_internal(song_id: int):
    """Internal play function that doesn't spawn a new watcher thread."""
    global _current_id, _is_paused

    song = get_music_by_id(song_id)
    if not song or not os.path.exists(song["location"]):
        return

    try:
        pygame.mixer.music.load(song["location"])
        pygame.mixer.music.play()
        _current_id = song_id
        _is_paused = False
    except Exception:
        pass

# ────────────────────────────────────────────────────────────────────

DB_PATH = "identifier.sqlite"
MUSIC_DIR = os.path.join(os.path.expanduser("~"), "Documents", "music")


# ── Setup ────────────────────────────────────────────────────────────────────

def init_db():
    os.makedirs(MUSIC_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
                     CREATE TABLE IF NOT EXISTS music
                     (
                         id
                         INTEGER
                         PRIMARY
                         KEY
                         AUTOINCREMENT,
                         name
                         TEXT
                         NOT
                         NULL,
                         location
                         TEXT
                         NOT
                         NULL
                         UNIQUE
                     )
                     """)
        conn.execute("DELETE FROM music WHERE location = '__pending__'")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'music' AND NOT EXISTS (SELECT 1 FROM music)")
        conn.commit()


# ── Auto-detect and inject paths ──────────────────────────────────────────────
def _inject_paths():
    paths_to_add = []

    for path in [
        r"C:\Program Files\nodejs",
        r"C:\Program Files (x86)\nodejs",
        os.path.expandvars(r"%APPDATA%\nvm\current"),
    ]:
        if os.path.exists(path):
            paths_to_add.append(path)
            break

    winget_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.exists(winget_dir):
        for folder in os.listdir(winget_dir):
            if "ffmpeg" in folder.lower():
                for root, dirs, files in os.walk(os.path.join(winget_dir, folder)):
                    if "ffmpeg.exe" in files:
                        paths_to_add.append(root)
                        break

    for path in [
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files (x86)\ffmpeg\bin",
    ]:
        if os.path.exists(path):
            paths_to_add.append(path)
            break

    if paths_to_add:
        os.environ["PATH"] = os.pathsep.join(paths_to_add) + os.pathsep + os.environ.get("PATH", "")


_inject_paths()


# ── Store ────────────────────────────────────────────────────────────────────

def store_music(youtube_url: str) -> int:
    ydl_opts_info = {"quiet": True}

    try:
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            name = info.get("title", "unknown")
    except Exception as e:
        raise e

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM music WHERE location = '__pending__'")
        cursor = conn.execute(
            "INSERT INTO music (name, location) VALUES (?, ?)",
            (name, "__pending__")
        )
        song_id = cursor.lastrowid
        conn.commit()

    safe_name = re.sub(r'[^\w\s-]', '', name.encode('ascii', 'ignore').decode())
    safe_name = re.sub(r'[\s]+', '_', safe_name)
    filename = f"{safe_name}_{song_id}"
    dest_path = os.path.join(MUSIC_DIR, filename)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": dest_path,
        "quiet": False,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])

    final_path = dest_path + ".mp3"

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE music SET location = ? WHERE id = ?", (final_path, song_id))
        conn.commit()

    print(f"[store] '{name}' saved → {final_path}  (id={song_id})")
    return song_id

# ── Retrieve ─────────────────────────────────────────────────────────────────

def get_all_music() -> list[dict]:
    """Return all songs as a list of dicts."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM music ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def search_music(query: str) -> list[dict]:
    """Search songs by name (case-insensitive partial match)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM music WHERE name LIKE ?", (f"%{query}%",)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_music(song_id: int):
    global _stop_watcher

    song = get_music_by_id(song_id)
    if not song:
        print(f"[delete] No song with id={song_id}")
        return

    _stop_watcher = True
    time.sleep(0.2)

    try:
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
    except:
        pass

    if os.path.exists(song["location"]):
        os.remove(song["location"])

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM music WHERE id = ?", (song_id,))
        conn.commit()

    print(f"[delete] '{song['name']}' (id={song_id}) removed")


# ── Playback ──────────────────────────────────────────────────────────────────

def get_music_by_id(song_id: int) -> dict | None:
    """Return a single song by ID, or None if not found."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM music WHERE id = ?", (song_id,)
        ).fetchone()
    return dict(row) if row else None


def play_music(song_id: int):
    global _current_id, _advance_thread, _is_paused, _stop_watcher

    song = get_music_by_id(song_id)
    if not song:
        print(f"[play] No song with id={song_id}")
        return

    if not os.path.exists(song["location"]):
        print(f"[play] File not found → {song['location']}")
        return

    _stop_watcher = True
    _stop_event.set()

    # FIX 3: Don't join current thread (auto-advance calls play_music from watcher thread)
    if _advance_thread and _advance_thread.is_alive() and threading.current_thread() != _advance_thread:
        _advance_thread.join(timeout=2.0)

    _stop_watcher = False
    _stop_event.clear()

    # FIX 4: Only init mixer if not already initialized — avoids reset/glitch on every song
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)

    try:
        pygame.mixer.music.load(song["location"])
        pygame.mixer.music.play()
        pygame.mixer.music.set_endevent(pygame.USEREVENT)
    except Exception:
        pass

    _current_id = song_id
    _is_paused = False
    print(f"[▶] Now playing: '{song['name']}' (id={song_id})")

    _advance_thread = threading.Thread(target=_watch_and_advance, daemon=True)
    _advance_thread.start()


def stop_music():
    """Stop playback completely."""
    global _stop_watcher, _current_id, _is_paused

    _stop_watcher = True
    pygame.mixer.music.stop()
    _current_id = None
    _is_paused = False
    print("[■] Stopped")


def pause_music():
    """Pause playback."""
    global _is_paused
    pygame.mixer.music.pause()
    _is_paused = True
    print("[⏸] Paused")


def resume_music():
    """Resume paused playback."""
    global _is_paused
    pygame.mixer.music.unpause()
    _is_paused = False
    print("[▶] Resumed")


def is_playing() -> bool:
    """Returns True if music is currently playing (not paused)."""
    return pygame.mixer.music.get_busy() and not _is_paused


def is_paused() -> bool:
    """Returns True if music is paused."""
    return _is_paused


# ── Manual Next/Previous functions ────────────────────────────────────────────

def next_music():
    """Manually skip to the next song."""
    global _current_id, _stop_watcher

    if _current_id is None:
        all_songs = get_all_music()
        if all_songs:
            play_music(all_songs[0]["id"])
        return

    all_songs = get_all_music()
    if not all_songs:
        print("[next] No songs available")
        return

    ids = [s["id"] for s in all_songs]

    if _current_id in ids:
        idx = ids.index(_current_id)
        next_idx = (idx + 1) % len(ids)
        next_id = ids[next_idx]
    else:
        next_id = ids[0]

    _stop_watcher = True
    play_music(next_id)


def previous_music():
    """Go back to the previous song."""
    global _current_id, _stop_watcher

    if _current_id is None:
        all_songs = get_all_music()
        if all_songs:
            play_music(all_songs[-1]["id"])
        return

    all_songs = get_all_music()
    if not all_songs:
        print("[previous] No songs available")
        return

    ids = [s["id"] for s in all_songs]

    if _current_id in ids:
        idx = ids.index(_current_id)
        prev_idx = (idx - 1) % len(ids)
        prev_id = ids[prev_idx]
    else:
        prev_id = ids[-1]

    _stop_watcher = True
    play_music(prev_id)


def get_current_song() -> dict | None:
    """Get the currently playing song information."""
    global _current_id
    if _current_id is None:
        return None
    return get_music_by_id(_current_id)


# ── Loop state ────────────────────────────────────────────────────────────────

def toggle_loop() -> bool:
    global _loop
    _loop = not _loop
    print(f"[🔁] Loop: {'ON' if _loop else 'OFF'}")
    return _loop


def is_loop() -> bool:
    return _loop