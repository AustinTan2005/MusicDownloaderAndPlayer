import os
import time
import threading
import sys
import yt_dlp
from functions import (
    toggle_loop, is_loop, init_db, play_music, stop_music,
    pause_music, resume_music, is_playing, get_all_music,
    store_music, delete_music, search_music, get_current_song,
    next_music, previous_music, is_paused
)

# For Windows non-blocking input
if os.name == 'nt':
    import msvcrt


    def get_key_with_timeout(timeout=0.5):
        """Get a key press with timeout (Windows)."""
        start = time.time()
        while (time.time() - start) < timeout:
            if msvcrt.kbhit():
                return msvcrt.getch().decode('utf-8', errors='ignore')
            time.sleep(0.05)
        return None
else:
    import select


    def get_key_with_timeout(timeout=0.5):
        """Get a key press with timeout (Unix)."""
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            return sys.stdin.read(1)
        return None

def clear():
    os.system("cls" if os.name == "nt" else "clear")
    print("\033[H\033[J", end="")


def playback_menu(song_id: int):
    """Event-driven playback menu - refreshes only on input or song change."""
    play_music(song_id)
    last_song_id = song_id

    # Initial display
    def display():
        clear()
        current = get_current_song()
        if not current:
            return None

        current_id = current['id']
        current_name = current['name']

        # Display status
        if is_paused():
            status = "⏸ Paused"
        elif is_playing():
            status = "▶ Playing"
        else:
            status = "■ Stopped"

        loop_status = "🔁 ON" if is_loop() else "🔁 OFF"

        print(f"── Now Playing (id={current_id}) ──")
        print(f"{status}  |  Loop: {loop_status}")
        print(f"♪ {current_name}\n")
        print("─────────────────────────────────")
        print("Commands:")
        print("  [1] Pause / Resume")
        print("  [2] Toggle Loop")
        print("  [3] Next Song")
        print("  [4] Previous Song")
        print("  [5] Stop & go back")
        print("─────────────────────────────────")
        print("\nWaiting for input (refreshes on song change)...")

        return current_id

    current_id = display()

    while True:
        # Check for song change (auto-advance happened)
        current = get_current_song()
        if not current:
            print("\nPlayback stopped.")
            time.sleep(1)
            break

        if current['id'] != last_song_id:
            # Song changed - refresh display
            last_song_id = current['id']
            current_id = display()

        # Non-blocking input check
        key = get_key_with_timeout(timeout=0.3)

        if key:
            # User pressed a key - handle it and refresh
            if key == '1':
                if is_paused():
                    resume_music()
                else:
                    pause_music()
                current_id = display()

            elif key == '2':
                toggle_loop()
                current_id = display()

            elif key == '3':
                next_music()
                time.sleep(0.2)  # Give it a moment to load
                last_song_id = get_current_song()['id'] if get_current_song() else None
                current_id = display()

            elif key == '4':
                previous_music()
                time.sleep(0.2)
                last_song_id = get_current_song()['id'] if get_current_song() else None
                current_id = display()

            elif key == '5':
                stop_music()
                break


def menu():
    clear()
    print("── Music Player ─────────────────")
    print("1. Get all music")
    print("2. Store music (YouTube URL)")
    print("3. Delete music")
    print("4. Search music")
    print("5. Exit")
    print("─────────────────────────────────")

    choice = input("Enter your choice: ").strip()

    if choice == "1":
        clear()
        songs = get_all_music()
        if not songs:
            print("No music found.")
            input("\nPress Enter to go back...")
            return

        print("Available Songs:")
        for song in songs:
            print(f"  [{song['id']}] {song['name']}")

        try:
            song_id = int(input("\nWhich music do you want to play? (ID): "))
            playback_menu(song_id)
        except ValueError:
            print("Invalid ID.")
            time.sleep(1)

    elif choice == "2":
        clear()
        url = input("Enter the YouTube URL (or 'back' to cancel): ").strip()
        if url.lower() in ["back", "b"]:
            return
        try:
            print("\nDownloading...")
            store_music(url)
            print("✓ Music stored successfully!")
        except Exception as e:
            print(f"✗ Error: {e}")
        input("\nPress Enter to go back...")

    elif choice == "3":
        clear()
        songs = get_all_music()
        if not songs:
            print("No music found.")
            input("\nPress Enter to go back...")
            return

        print("Available Songs:")
        for song in songs:
            print(f"  [{song['id']}] {song['name']}")

        try:
            song_id = int(input("\nEnter the ID of the music to delete: "))
            delete_music(song_id)
            print("✓ Music deleted successfully!")
        except ValueError:
            print("✗ Invalid ID.")
        except Exception as e:
            print(f"✗ Error: {e}")
        input("\nPress Enter to go back...")

    elif choice == "4":
        clear()
        query = input("Search: ").strip()
        results = search_music(query)

        if not results:
            print("No results found.")
        else:
            print("\nSearch Results:")
            for song in results:
                print(f"  [{song['id']}] {song['name']}")

        input("\nPress Enter to go back...")

    elif choice == "5":
        clear()
        print("Goodbye! 👋")
        exit()

    else:
        print("Invalid choice.")
        time.sleep(0.5)


if __name__ == "__main__":
    init_db()

    while True:
        try:
            menu()
        except KeyboardInterrupt:
            clear()
            print("\n\nGoodbye! 👋\n")
            break
        except Exception as e:
            print(f"\nError: {e}")
            input("\nPress Enter to continue...")