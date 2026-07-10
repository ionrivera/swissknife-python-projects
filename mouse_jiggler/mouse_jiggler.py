# mouse_jiggler.py
import pyautogui
import time
import random
import os
import glob
import json

# Configuration
ACTIVITY_INTERVAL = 60
QUOTE_FILE = "quotes.txt"
CONFIG_FILE = ".jiggler.conf"  # Stores current state for persistence

# ANSI Color Codes
GREEN = "\033[92m"
BLUE = "\033[94m"
RESET = "\033[0m"

# Stoic Virtues for the "Theme of the Day"
VIRTUES = {
    "Wisdom": "Prioritize what you can control; ignore the rest.",
    "Justice": "Do the right thing, even if no one is watching.",
    "Courage": "Face your tasks with steady resolve, not complaint.",
    "Temperance": "Do not be mastered by your impulses or your inbox."
}

def load_quotes():
    """Loads quotes from a text file, one per line."""
    default_quotes = [
        "Be tolerant with others and strict with yourself. - Marcus Aurelius",
        "We suffer more often in imagination than in reality. - Seneca",
        "No man is free who is not master of himself. - Epictetus",
        "The best revenge is to be unlike him who performed the injury. - Marcus Aurelius"
    ]
    
    if not os.path.exists(QUOTE_FILE):
        return default_quotes
    
    with open(QUOTE_FILE, "r", encoding="utf-8") as f:
        quotes = [line.strip() for line in f if line.strip()]
    
    return quotes if quotes else default_quotes

def get_ascii_files():
    """Returns list of files starting with 'ascii_' sorted in ascending order."""
    return sorted(glob.glob("ascii_*"))

def load_file_content(filepath):
    """Reads lines from a specific file."""
    if not filepath or not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return [line.rstrip() for line in f.readlines()]
    except Exception:
        return None

def save_state(current_file, line_index):
    """Saves the current file and line position to a config file."""
    state = {
        "last_file": current_file,
        "line_index": line_index
    }
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"Failed to save state: {e}")

def load_state():
    """Loads the last saved state."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"last_file": None, "line_index": 0}

def start_jiggler():
    quotes = load_quotes()
    
    # Theme of the Day Logic
    theme, focus = random.choice(list(VIRTUES.items()))
    
    # Load persistence data
    state = load_state()
    last_file = state.get("last_file")
    line_index = state.get("line_index", 0)

    # Get file list (always ascending)
    file_list = get_ascii_files()
    
    # Find where we left off in the file list
    file_index = 0
    if last_file in file_list:
        file_index = file_list.index(last_file)
    
    print("==========================================")
    print(f"   THEME OF THE DAY: {theme.upper()}")
    print(f"   Focus: {focus}")
    print("==========================================\n")
    print(f"Status: Active ({len(quotes)} quotes loaded)")
    print(f"Logic: Resume from last known line. Order: Ascending.")
    print("Press Ctrl+C to exit.\n")

    current_art = None
    if file_list:
        current_art = load_file_content(file_list[file_index])

    try:
        while True:
            # Simulate activity
            pyautogui.press('shift')
            timestamp = time.strftime('%H:%M:%S')

            # 1. Logic to handle "Unfolding" and Sequential File Selection
            # If no art is loaded or we finished the current one
            if not current_art or line_index >= len(current_art):
                
                # Move to next file or restart list
                file_index = (file_index + 1) if current_art else file_index
                if file_index >= len(file_list):
                    file_index = 0
                    print(f"--- All artwork shown. Restarting ascending sequence ---\n")

                if file_list:
                    current_art = load_file_content(file_list[file_index])
                    line_index = 0
                else:
                    current_art = None

            # 2. Display logic
            if current_art:
                # Print current line in GREEN
                current_file_path = file_list[file_index]
                print(f"[{timestamp}] {GREEN}{current_art[line_index]}{RESET}")
                
                # Save state BEFORE incrementing, so we resume on this exact line
                line_index += 1
                save_state(current_file_path, line_index)
                
                # If that was the last line of the current file, follow up with a quote
                if line_index >= len(current_art):
                    current_quote = random.choice(quotes)
                    print(f"\n{BLUE}--- WISDOM REVEALED ---")
                    print(f"{current_quote}{RESET}")
                    print("-" * 23 + "\n")
            else:
                # Fallback if no ASCII files exist
                current_quote = random.choice(quotes)
                print(f"[{timestamp}] {BLUE}{current_quote}{RESET}")
            
            # Wait for the next interval
            time.sleep(ACTIVITY_INTERVAL)

    except KeyboardInterrupt:
        print("\n[Terminated] State saved. Return to the present moment.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    start_jiggler()