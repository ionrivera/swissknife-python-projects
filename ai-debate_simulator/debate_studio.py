import tkinter as tk
from tkinter import scrolledtext
from google import genai
from google.genai import types
from google.genai.errors import APIError
import threading
import logging
import time
import os
import asyncio
import edge_tts
import pygame

# --- CONFIGURE ERROR LOGGING ---
logging.basicConfig(
    filename='debate_studio_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- CONFIGURATION ---
MODEL_NAME = "gemini-2.5-flash" 

# Highly localized natural neural voices for Tagalog speakers
VOICE_MALE = "fil-PH-AngeloNeural"
VOICE_FEMALE = "fil-PH-BlessicaNeural"

SYSTEM_PROMPT_MALE = (
    "Ikaw si Atty. Rudy Sebastian, kinakatawan ang Duterte Party / Maisug faction. "
    "Ang iyong tono ay populista, matalas, agresibo, at direktang sumasagot. "
    "Gumamit ng wikang Tagalog na may halong lokal na kontekstong pampulitika at eksaktong mga Article o section ng batas bilang reference. "
    "TUMUTOK LAMANG SA PAKSANG IBINIGAY SA IYO. Huwag magpasok ng ibang isyu tulad ng "
    "foreign policy o pambansang pananalapi maliban na lamang kung ito ay direktang bahagi ng paksa. "
    "Panatilihing maikli, palaban, at hindi lalampas sa 3 siksik na talata ang iyong mga sagot."
)

SYSTEM_PROMPT_FEMALE = (
    "Ikaw si Sec. Maricar Valenzuela, kinakatawan ang Pro-Admin / Bagong Pilipinas faction. "
    "Ang iyong tono ay propesyonal, kalmado, korporatibo, artikulado, nakabatay sa mga datos at eksaktong mga Article o section ng batas bilang reference. "
    "Gumamit ng wikang Tagalog. TUMUTOK LAMANG SA PAKSANG IBINIGAY SA IYO. Huwag lumihis sa "
    "ibang usapin na walang kinalaman sa tinatalakay na isyu. "
    "Direktang kalasin ang mga pahayag ng oposisyon gamit ang lohika. Panatilihing hindi lalampas sa 3 siksik na talata ang iyong tugon."
)

class DebateStudio:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Political Debate Studio - Green Screen Panel")
        self.root.geometry("900x750")
        
        # Solid green screen background
        self.root.configure(bg="#00FF00")
        
        # Initialize Audio Player Mixer
        pygame.mixer.init()
        
        # Initialize Google GenAI Client
        try:
            self.client = genai.Client()
        except Exception as e:
            logging.error("Failed to initialize Gemini Client. Check your API key.", exc_info=True)
            self.client = None
        
        # Track historical exchanges
        self.history_male = []
        self.history_female = []
        
        self.turn_counter = 1
        self.is_debating = False
        self.topic = ""
        
        self.build_ui()

    def build_ui(self):
        try:
            # Topic Input Section Frame
            self.input_frame = tk.Frame(self.root, bg="#111111", pady=10)
            self.input_frame.pack(pady=10, fill=tk.X, padx=20)
            
            self.input_label = tk.Label(
                self.input_frame, text="PAKSANG PAGDEBATAHAN (DEBATE TOPIC):", 
                font=("Helvetica", 10, "bold"), fg="white", bg="#111111"
            )
            self.input_label.pack(anchor=tk.W, padx=10)
            
            self.topic_entry = tk.Entry(self.input_frame, font=("Helvetica", 11), width=80)
            self.topic_entry.pack(fill=tk.X, padx=10, pady=5)
            self.topic_entry.insert(0, "Ang kasalukuyang direksyon ng paglago ng ekonomiya at alokasyon ng imprastraktura sa Pilipinas.")
            
            # Main Text Terminal Monitor
            self.monitor = scrolledtext.ScrolledText(
                self.root, font=("Consolas", 11), fg="#00FF00", bg="#111111", 
                wrap=tk.WORD, bd=0, highlightthickness=0
            )
            self.monitor.pack(pady=10, fill=tk.BOTH, expand=True, padx=20)
            self.clear_and_reset_monitor()
            
            # Control Dashboard Buttons
            self.btn_frame = tk.Frame(self.root, bg="#00FF00")
            self.btn_frame.pack(pady=15)
            
            self.next_btn = tk.Button(
                self.btn_frame, text="Start Next Turn ▶", font=("Helvetica", 11, "bold"),
                bg="#222222", fg="white", width=20, command=self.trigger_next_turn
            )
            self.next_btn.pack(side=tk.LEFT, padx=10)

            self.reset_btn = tk.Button(
                self.btn_frame, text="Reset Session ↺", font=("Helvetica", 11, "bold"),
                bg="#441111", fg="white", width=18, command=self.reset_debate
            )
            self.reset_btn.pack(side=tk.LEFT, padx=10)
            
        except Exception as e:
            logging.error("Fatal exception during UI construction", exc_info=True)
            raise e

    def clear_and_reset_monitor(self):
        self.monitor.config(state=tk.NORMAL)
        self.monitor.delete("1.0", tk.END)
        self.monitor.insert(tk.END, "=== SYSTEM READY. Set your topic above and click 'Start Next Turn' to begin. ===\n")
        self.monitor.insert(tk.END, "=== This standard debate consists of 4 turns ending with a closing statement. ===\n\n")
        self.monitor.config(state=tk.DISABLED)

    def log_to_monitor(self, speaker_name, text):
        self.monitor.config(state=tk.NORMAL)
        self.monitor.insert(tk.END, f"[{speaker_name.upper()}]\n", "header")
        self.monitor.insert(tk.END, f"{text}\n\n---------------------------------------------\n\n")
        self.monitor.see(tk.END)
        self.monitor.config(state=tk.DISABLED)

    def trigger_next_turn(self):
        if self.is_debating:
            return
        
        if not self.client:
            self.log_to_monitor("SYSTEM ERROR", "Gemini Client not initialized. Please set the GEMINI_API_KEY environment variable.")
            return

        if self.turn_counter == 1:
            self.topic = self.topic_entry.get().strip()
            self.topic_entry.config(state=tk.DISABLED)
            
        self.is_debating = True
        self.next_btn.config(state=tk.DISABLED)
        
        threading.Thread(target=self.process_debate_turn, daemon=True).start()

    def play_voice_override(self, text, voice_name):
        """Asynchronously synthesizes speech using edge-tts and plays it immediately"""
        try:
            temp_file = "temp_debate_voice.mp3"
            
            # Define loop logic to extract and run edge-tts inside worker thread smoothly
            async def run_tts():
                communicate = edge_tts.Communicate(text, voice_name)
                await communicate.save(temp_file)
                
            asyncio.run(run_tts())
            
            # Play generated tracking asset via pygame context layers
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                
            pygame.mixer.music.unload()
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception as e:
            logging.error("Failed handling voice synthesis layer", exc_info=True)

    def generate_with_retry(self, contents, config):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(model=MODEL_NAME, contents=contents, config=config)
                return response.text
            except APIError as e:
                if e.code == 503 and attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                raise e

    def process_debate_turn(self):
        try:
            # Check standard 4-turn boundary cap limits
            if self.turn_counter > 4:
                self.log_to_monitor("SYSTEM", "Tapos na ang opisyal na debate. I-click ang 'Reset Session' upang magsimula muli.")
                return

            if self.turn_counter == 1:
                prompt = f"Magbigay ng iyong pambungad na argumento tungkol sa paksang ito: {self.topic}. Kausapin nang direkta ang mga manonood gamit ang Tagalog."
                self.history_male.append({"role": "user", "content": prompt})
                
                contents = [types.Content(role=m["role"], parts=[types.Part.from_text(text=m["content"])]) for m in self.history_male]
                config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT_MALE)
                
                reply_text = self.generate_with_retry(contents, config)
                self.history_male.append({"role": "model", "content": reply_text})
                
                self.log_to_monitor("Atty. Rudy Sebastian (Oposisyon) - Opening", reply_text)
                self.play_voice_override(reply_text, VOICE_MALE)
                
                self.history_female.append({"role": "user", "content": f"Ang sabi ng iyong katunggali na si Atty. Rudy Sebastian: '{reply_text}'. Ibigay ang iyong pambungad na pahayag at direktang sagutin o pabulaanan ang kanyang mga argumento gamit ang Tagalog."})
                self.turn_counter += 1
                
            elif self.turn_counter == 2:
                contents = [types.Content(role=m["role"], parts=[types.Part.from_text(text=m["content"])]) for m in self.history_female]
                config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT_FEMALE)
                
                reply_text = self.generate_with_retry(contents, config)
                self.history_female.append({"role": "model", "content": reply_text})
                
                self.log_to_monitor("Sec. Maricar Valenzuela (Pro-Admin) - Response", reply_text)
                self.play_voice_override(reply_text, VOICE_FEMALE)
                
                self.history_male.append({"role": "user", "content": f"Sumagot si Sec. Maricar Valenzuela ng: '{reply_text}'. Ibigay ang iyong panghuling counter-rebuttal gamit ang Tagalog."})
                self.turn_counter += 1
                
            elif self.turn_counter == 3:
                contents = [types.Content(role=m["role"], parts=[types.Part.from_text(text=m["content"])]) for m in self.history_male]
                config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT_MALE)
                
                reply_text = self.generate_with_retry(contents, config)
                self.history_male.append({"role": "model", "content": reply_text})
                
                self.log_to_monitor("Atty. Rudy Sebastian (Oposisyon) - Final Counter", reply_text)
                self.play_voice_override(reply_text, VOICE_MALE)
                
                self.history_female.append({"role": "user", "content": f"Nangatwiran si Atty. Rudy Sebastian ng: '{reply_text}'. Ibigay ang iyong panghuling konklusyon o closing summary upang tapusin ang debate gamit ang Tagalog."})
                self.turn_counter += 1
                
            elif self.turn_counter == 4:
                contents = [types.Content(role=m["role"], parts=[types.Part.from_text(text=m["content"])]) for m in self.history_female]
                config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT_FEMALE)
                
                reply_text = self.generate_with_retry(contents, config)
                self.history_female.append({"role": "model", "content": reply_text})
                
                self.log_to_monitor("Sec. Maricar Valenzuela (Pro-Admin) - Closing Statement", reply_text)
                self.play_voice_override(reply_text, VOICE_FEMALE)
                
                # Graceful conclusion block execution
                self.log_to_monitor("SYSTEM", "=== ANG DEBATE AY OPISYAL NANG TAPOS. ===")
                self.turn_counter += 1

        except Exception as e:
            logging.error("Exception handled during debate processing turn", exc_info=True)
            self.log_to_monitor("SYSTEM ERROR", f"Maling naganap. Error: {str(e)}")
            
        finally:
            self.is_debating = False
            # Keep next turn disabled permanently if the debate sequence has concluded
            if self.turn_counter <= 4:
                self.next_btn.config(state=tk.NORMAL)

    def reset_debate(self):
        if self.is_debating:
            return
        pygame.mixer.music.stop()
        self.history_male = []
        self.history_female = []
        self.turn_counter = 1
        self.topic = ""
        self.topic_entry.config(state=tk.NORMAL)
        self.clear_and_reset_monitor()
        self.next_btn.config(state=tk.NORMAL)

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = DebateStudio(root)
        root.mainloop()
    except Exception as e:
        logging.critical("Application failed at root execution level", exc_info=True)