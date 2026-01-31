import threading
import speech_recognition as sr
from deep_translator import GoogleTranslator
import queue, time, io, datetime, os
import asyncio
import edge_tts
import pygame
import streamlit as st
import logging


# ================== LOGGING ==================
logging.basicConfig(
    filename='nova_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.info("--- NOVA TRANSMIT STARTUP ---")

# ================== SETTINGS & CONSTS ==================
CORRECTIONS = {
    "chat gpt": "ChatGPT",
    "you tube": "YouTube",
    "mine craft": "Minecraft",
    "ram sathvik": "Ram Sathvik",
    "open ai": "OpenAI"
}

ACCENTS = {
    "en": ["en-US", "en-GB", "en-IN", "en-AU", "en-CA", "en-NZ"],
    "es": ["es-ES", "es-MX", "es-US", "es-AR", "es-CO"],
    "fr": ["fr-FR", "fr-CA", "fr-BE", "fr-CH"],
    "de": ["de-DE", "de-AT", "de-CH"],
    "it": ["it-IT", "it-CH"],
    "pt": ["pt-PT", "pt-BR"],
    "ar": ["ar-SA", "ar-EG", "ar-AE"],
    "ru": ["ru-RU"],
    "ja": ["ja-JP"],
    "ko": ["ko-KR"],
    "zh": ["zh-CN", "zh-TW"],
    "hi": ["hi-IN"],
    "te": ["te-IN"],
    "ta": ["ta-IN"],
    "kn": ["kn-IN"],
    "ml": ["ml-IN"],
    "bn": ["bn-IN"],
    "gu": ["gu-IN"],
    "mr": ["mr-IN"],
    "nl": ["nl-NL", "nl-BE"],
    "tr": ["tr-TR"],
    "pl": ["pl-PL"],
    "sv": ["sv-SE"],
    "da": ["da-DK"],
    "fi": ["fi-FI"],
    "no": ["nb-NO"],
}


def fix_words(text):
    t = text.lower()
    for k, v in CORRECTIONS.items():
        t = t.replace(k, v.lower())
    return t.title()

# ================== STATE ==================
class TranslatorState:
    def __init__(self):
        # Recognizer removed from here to prevent module-level memory issues
        self.tts_queue = queue.Queue()
        self.audio_chunk_queue = queue.Queue() 
        self.stop_event = threading.Event()
        self.speaking_event = threading.Event()
        self.active_threads = []
        self.run_id = [0]
        self._manual_stop = False
        self.is_running = False
        
        self.history = []
        self.history_version = 0
        self.status_msg = "Ready"
        self.error_msg = ""
        self.worker_status = {"Capture": "Idle", "Processor": "Idle", "TTS": "Idle"}
        self.mic_list = None # Cached list of microphones
        
        # Internal True Source of Truth
        self.settings = {
            "speaker_a_lang": "en", "speaker_a_locale": "en-US",
            "speaker_b_lang": "hi", "speaker_b_locale": "hi-IN",
            "active_speaker": "A", "sensitivity": 120, "voice_speed": 1.0,
            "noise_reduction": False,
            "device_index": None # Default to system default
        }
        
        self.live_caption = ""
        self.live_translation = ""
        self.lock = threading.RLock() # Changed to RLock to prevent deadlocks
        
        self.loop = None
        self._hardware_initialized = False

    def initialize_hardware(self):
        with self.lock:
            if self._hardware_initialized: return
            
            # ONLY init pygame if TTS is NOT disabled
            if not self.settings.get('disable_tts_debug', False):
                try: 
                    logger.info("HARDWARE: Initializing Pygame Mixer")
                    pygame.mixer.quit()
                    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=1024) 
                except Exception as e: 
                    logger.error(f"HARDWARE: Pygame Init Failed: {e}")
                
                try:
                    logger.info("HARDWARE: Starting Asyncio Loop Thread")
                    self.loop = asyncio.new_event_loop()
                    threading.Thread(target=self._start_loop, daemon=True, name="AsyncLoop").start()
                except Exception as e:
                    logger.error(f"HARDWARE: Asyncio Init Failed: {e}")

            self._hardware_initialized = True

    def _start_loop(self):
        if self.loop:
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()

    def add_history(self, original, translated, src_lang, tgt_lang, speaker):
        with self.lock:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            entry = {
                "timestamp": ts, "original": original, "translated": translated,
                "src_lang": src_lang, "tgt_lang": tgt_lang,
                "speaker": speaker, "confidence": 1.0
            }
            self.history.insert(0, entry)
            self.history_version += 1
            self.live_caption = ""
            self.live_translation = ""

    def start_session(self):
        with self.lock:
            if self.is_running: return 
            self.is_running = True
            
            # Ensure hardware components are ready
            self.initialize_hardware()
            
            self.stop_event.clear()
            self._manual_stop = False
            self.run_id[0] += 1
            rid = self.run_id[0]
            
            self.active_threads = [
                threading.Thread(target=audio_capture_worker, args=(rid,), daemon=True, name="Capture"),
                threading.Thread(target=streaming_processor_worker, args=(rid,), daemon=True, name="Processor"),
                threading.Thread(target=finalization_timer_worker, args=(rid,), daemon=True, name="Timer"),
                threading.Thread(target=tts_worker, args=(rid,), daemon=True, name="TTS")
            ]
            
            # Debug: Allow disabling workers to isolate crash
            if state.settings.get('disable_mic_debug', False):
                logger.info("DEBUG: Capture thread skipped by setting")
                self.active_threads = [t for t in self.active_threads if t.name != "Capture"]
            
            if state.settings.get('disable_tts_debug', False):
                logger.info("DEBUG: TTS thread skipped by setting")
                self.active_threads = [t for t in self.active_threads if t.name != "TTS"]
            
            for t in self.active_threads: 
                logger.info(f"RENDER: Starting thread: {t.name}")
                t.start()
            
            logger.info(f"🚀 [SESSION {rid}] Threads Started (Complete)")
            print(f"🚀 [SESSION {rid}] Threads Started")

    def stop_session(self):
        with self.lock:
            self.is_running = False
            self._manual_stop = True
            self.stop_event.set()
            # Flush queues and stop music
            try: pygame.mixer.music.stop()
            except: pass
            
            while not self.tts_queue.empty():
                try: self.tts_queue.get_nowait()
                except: break
            while not self.audio_chunk_queue.empty():
                try: self.audio_chunk_queue.get_nowait()
                except: break
            
            self.speaking_event.clear()
            print("🛑 Session Stopped")

    @property
    def threads_active(self):
        return self.is_running

# State versioning replaced with robust session_state management
if 'state_v24' not in st.session_state:
    logger.info("STATE: Creating new TranslatorState (v24)")
    st.session_state.state_v24 = TranslatorState()

state = st.session_state.state_v24

@st.cache_data
def load_languages():
    try:
        translator = GoogleTranslator(source="auto", target="en")
        langs = translator.get_supported_languages(as_dict=True)
        return {code: name.capitalize() for name, code in langs.items()}
    except Exception:
        return {"en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French", "te": "Telugu", "ta": "Tamil"}

LANGS = load_languages()

@st.cache_resource
def get_dynamic_voice_map():
    """
    Dynamically fetches available voices from edge-tts and builds a robust mapping.
    Maps both full locales (e.g. 'en-US') and short codes (e.g. 'en') to voice names.
    """
    try:
        # Run async list_voices in a way that doesn't conflict with existing loops
        # Since this is cached resource, it runs once at startup
        voice_list = asyncio.run(edge_tts.list_voices())
        
        v_map = {}
        for v in voice_list:
            short_name = v['ShortName']
            locale = v['Locale']
            lang_code = locale.split('-')[0]
            
            # Map the full locale (e.g., zh-CN -> zh-CN-YunxiNeural)
            if locale not in v_map:
                v_map[locale] = short_name
            
            # Map the short code (e.g., zh -> zh-CN-YunxiNeural)
            # Prefer Neural voices for short code fallback
            if lang_code not in v_map:
                v_map[lang_code] = short_name
            else:
                # If we already have a mapping for the short code, update it only if the new one is "Neural" 
                # and the current one isn't (though most edge-tts are neural now)
                # Or maybe prefer specific regions (like US for en). 
                # For now, first-come or simple overwrite logic is fine, but let's stick to first found or specific update.
                pass
                
        return v_map
    except Exception as e:
        logger.error(f"Voice Map Init Error: {e}")
        # Fallback to the original hardcoded list if functionality fails
        return {
            "hi": "hi-IN-MadhurNeural", "te": "te-IN-MohanNeural", "ta": "ta-IN-ValluvarNeural",
            "kn": "kn-IN-GaganNeural", "ml": "ml-IN-MidhunNeural", "fr": "fr-FR-HenriNeural",
            "de": "de-DE-ConradNeural", "es": "es-ES-AlvaroNeural", "en": "en-US-AndrewNeural",
            "bn": "bn-IN-BashkarNeural", "gu": "gu-IN-DhwaniNeural", "mr": "mr-IN-AarohiNeural"
        }

VOICE_MAP = get_dynamic_voice_map()

# ================== AUDIO CORE ==================
def flush_audio():
    state.stop_session() # Use the robust stop
    state.status_msg = "🔊 Audio Flushed"

# ================== STREAMING WORKERS ==================
def audio_capture_worker(run_id):
    logger.info(f"Capture Worker Started (Run {run_id})")
    # Decouple recognizer - each thread gets its own
    r = sr.Recognizer()
    r.pause_threshold = 0.5 
    
    while not state.stop_event.is_set():
        if run_id != state.run_id[0]: break
        try:
            device_idx = state.settings.get('device_index')
            logger.info(f"HARDWARE: Attempting to open microphone (Index: {device_idx})")
            
            # CRITICAL: Keep source open for the ENTIRE duration of the run_id session
            # This prevents PortAudio from opening/closing drivers too rapidly which causes native crashes
            with sr.Microphone(device_index=device_idx) as source:
                logger.info("HARDWARE: Microphone Lock Acquired")
                while not state.stop_event.is_set():
                    if run_id != state.run_id[0]: break
                    
                    with state.lock: 
                        s = state.settings.copy()
                        r.energy_threshold = s['sensitivity']
                        state.worker_status["Capture"] = "🎤 Listening" if not state.speaking_event.is_set() else "⏸️ Paused"
                    
                    if s['noise_reduction']:
                        try:
                            logger.info("HARDWARE: Calibrating noise...")
                            state.worker_status["Capture"] = "🧬 Calibrating"
                            r.adjust_for_ambient_noise(source, duration=1.0)
                            with state.lock: state.settings['noise_reduction'] = False
                        except Exception as e:
                            logger.error(f"HARDWARE: Calibration Error: {e}")
                            with state.lock: state.error_msg = f"Calibration Error: {str(e)}"

                    if state.speaking_event.is_set():
                        time.sleep(0.1)
                        continue

                    try:
                        # Short timeout to keep loop responsive to stop_event
                        logger.debug("HARDWARE: Calling r.listen...")
                        audio = r.listen(source, phrase_time_limit=3.0, timeout=1.0)
                        logger.debug("HARDWARE: r.listen received audio")
                        state.audio_chunk_queue.put(audio)
                        with state.lock: state.error_msg = ""
                    except sr.WaitTimeoutError:
                        continue
                    except sr.UnknownValueError:
                        continue
                    except Exception as e:
                        logger.error(f"HARDWARE: Capture Loop Error: {e}")
                        with state.lock: 
                            state.error_msg = f"Capture Error: {str(e)}"
                            state.worker_status["Capture"] = "❌ Error"
                        time.sleep(1)
                        continue
            logger.info("HARDWARE: Microphone Lock Released")
        except Exception as e:
            logger.error(f"HARDWARE: Device CRITICAL Error: {e}")
            with state.lock: 
                state.error_msg = f"Device Init Error: {str(e)}"
                state.worker_status["Capture"] = "❌ Off"
            # Exponential backoff on hardware crash
            time.sleep(3)
            
    state.worker_status["Capture"] = "Idle"
    logger.info(f"Capture Worker Terminated (Run {run_id})")

def streaming_processor_worker(run_id):
    logger.info(f"Processor Worker Started (Run {run_id})")
    # Decouple recognizer - each thread gets its own
    r = sr.Recognizer()
    last_translation_time = time.time()
    while not state.stop_event.is_set():
        if run_id != state.run_id[0]: break
        try:
            audio = state.audio_chunk_queue.get(timeout=0.2)
            state.worker_status["Processor"] = "📡 Processing"
            with state.lock: s = state.settings.copy()
            
            if s['active_speaker'] == "A":
                src_lang, src_locale = s['speaker_a_lang'], s['speaker_a_locale']
                tgt_lang = s['speaker_b_lang']
            else:
                src_lang, src_locale = s['speaker_b_lang'], s['speaker_b_locale']
                tgt_lang = s['speaker_a_lang']

            try:
                # Use Google Speech Recognition
                text = r.recognize_google(audio, language=src_locale)
                if not text: 
                    state.worker_status["Processor"] = "Idle"
                    continue
                
                text = fix_words(text)
                
                with state.lock:
                    state.live_caption = (state.live_caption + " " + text).strip()
                    current_caption = state.live_caption
                
                # TRANSLATION OUTSIDE LOCK to prevent blocking
                if time.time() - last_translation_time > 0.5:
                    state.worker_status["Processor"] = f"☁️ {src_lang.upper()} -> {tgt_lang.upper()}"
                    try:
                        if src_lang == tgt_lang:
                            translated_text = current_caption
                        else:
                            translator = GoogleTranslator(source=src_lang, target=tgt_lang)
                            translated_text = translator.translate(current_caption)
                        
                        with state.lock:
                            state.live_translation = translated_text
                        last_translation_time = time.time()
                    except Exception as e:
                        with state.lock: state.error_msg = f"Translation Error: {str(e)}"
                
                with state.lock: state.history_version += 1
            except Exception as e: 
                state.worker_status["Processor"] = f"❓ Silence ({src_lang.upper()})"
                continue
        except: 
            state.worker_status["Processor"] = "Idle"
            continue

def finalization_timer_worker(run_id):
    last_caption = ""
    silence_start = time.time()
    while not state.stop_event.is_set():
        if run_id != state.run_id[0]: break
        with state.lock:
            current = state.live_caption
            translated = state.live_translation
            s = state.settings.copy()
        
        if current and current == last_caption:
            if time.time() - silence_start > 1.0: # Finalize after 2.2s of no new text
                if s['active_speaker'] == "A":
                    src, tgt = s['speaker_a_lang'], s['speaker_b_lang']
                else:
                    src, tgt = s['speaker_b_lang'], s['speaker_a_lang']
                
                state.add_history(current, translated, src, tgt, s['active_speaker'])
                with state.lock:
                    while not state.tts_queue.empty():
                        try: state.tts_queue.get_nowait()
                        except: break
                    state.tts_queue.put((run_id, translated, tgt))
                last_caption = ""
        else:
            last_caption = current
            silence_start = time.time()
        time.sleep(0.4)

def tts_worker(run_id):
    logger.info(f"TTS Worker Started (Run {run_id})")
    while not state.stop_event.is_set():
        if run_id != state.run_id[0]: break
        try:
            job_run, text, tgt_lang = state.tts_queue.get(timeout=0.2)
            state.worker_status["TTS"] = "🔊 Preparing"
            with state.lock: speed = state.settings['voice_speed']
            
            # Use global VOICE_MAP. Fallback to English if absolutely not found.
            # tgt_lang is usually a short code (e.g. 'fr', 'hi').
            # VOICE_MAP contains both short codes and full locales.
            voice = VOICE_MAP.get(tgt_lang, "en-US-AndrewNeural")

            rate = f"+{int((speed-1)*100)}%" if speed >= 1 else f"-{int((1-speed)*100)}%"
            
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            buf = io.BytesIO()
            async def save():
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio": buf.write(chunk["data"])
            asyncio.run_coroutine_threadsafe(save(), state.loop).result()
            
            buf.seek(0)
            state.speaking_event.set()
            state.worker_status["TTS"] = "📢 Speaking"
            pygame.mixer.music.load(buf)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if state.stop_event.is_set(): break
                time.sleep(0.01)
            state.speaking_event.clear()
            state.worker_status["TTS"] = "Idle"
        except: 
            state.speaking_event.clear()
            state.worker_status["TTS"] = "Idle"

def stop_all():
    state.stop_session()

# ================== UI ==================
def main():
    logger.debug("RENDER: Main loop started")
    st.set_page_config("Nova Transmit Pro", "🛰️", layout="wide")

    st.markdown("""
    <style>
    .stApp { background: #060709; color: #edeef0; }
    [data-testid="stSidebar"] { background: #0d1117; }
    .speaker-box { padding: 20px; border-radius: 12px; background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.08); }
    .active-box { border: 2px solid #00d4ff; box-shadow: 0 0 15px rgba(0, 212, 255, 0.1); }
    .caption-box { background: #11141a; padding: 25px; border-radius: 12px; border: 1px solid rgba(0, 212, 255, 0.3); }
    </style>
    """, unsafe_allow_html=True)

    # Initialize session state flags
    if "running" not in st.session_state: 
        st.session_state.running = False

    # Sync threads with session state
    logger.debug(f"RENDER: Running={st.session_state.running}, ThreadsActive={state.threads_active}")
    if st.session_state.running and not state.threads_active:
        logger.info("RENDER: Auto-starting session")
        state.start_session()
    elif not st.session_state.running and state.threads_active:
        logger.info("RENDER: Auto-stopping session")
        state.stop_session()

    with st.sidebar:
        st.header("🛰️ Nova Transmit")
        st.caption("Stabilized Engine v6.2")
        
        if not st.session_state.running:
            if st.button("🚀 INITIATE STREAM", use_container_width=True, type="primary"):
                st.session_state.running = True
        else:
            if st.button("🛑 TERMINATE STREAM", use_container_width=True):
                st.session_state.running = False
                state.stop_session()

      
        st.subheader("🎚️ Calibration")
        v_speed = st.slider("Speech Rate", 0.5, 2.0, state.settings['voice_speed'])
        v_sens = st.slider("Mic Gain (Sensitivity)", 10, 800, state.settings['sensitivity'])
        
        with state.lock:
            state.settings['voice_speed'] = v_speed
            state.settings['sensitivity'] = v_sens
        
        if st.button("🎵 Calibrate Mic"): 
            with state.lock: 
                state.settings['noise_reduction'] = True
                state.error_msg = "Calibrating..."
        if st.button("🧹 Flush Audio"): flush_audio()

        st.divider()
 
    c1, c2 = st.columns(2)
    with c1:
        is_a = state.settings['active_speaker'] == "A"
        st.markdown(f'<div class="speaker-box {"active-box" if is_a else ""}">🎙️ Station A </div>', unsafe_allow_html=True)
        
        # Language Selection
        lang_a = st.selectbox("Language A", list(LANGS.keys()), index=list(LANGS.keys()).index(state.settings['speaker_a_lang']), format_func=lambda x: LANGS[x], key="sa_lang")
        if lang_a != state.settings['speaker_a_lang']:
            with state.lock:
                state.settings['speaker_a_lang'] = lang_a
                state.settings['speaker_a_locale'] = ACCENTS.get(lang_a, [lang_a])[0]
                state.live_caption = ""
                state.live_translation = ""
        
        # Accent Selection
        acc_options_a = ACCENTS.get(state.settings['speaker_a_lang'], [state.settings['speaker_a_lang']])
        try: acc_idx_a = acc_options_a.index(state.settings['speaker_a_locale'])
        except: acc_idx_a = 0
        acc_a = st.selectbox("Accent A", acc_options_a, index=acc_idx_a, key="sa_acc")
        if acc_a != state.settings['speaker_a_locale']:
            with state.lock: 
                state.settings['speaker_a_locale'] = acc_a
                state.live_caption = ""
                state.live_translation = ""
            
        if st.button("Activate Station A", disabled=is_a, use_container_width=True):
            with state.lock: state.settings['active_speaker'] = "A"
            flush_audio()

    with c2:
        is_b = state.settings['active_speaker'] == "B"
        st.markdown(f'<div class="speaker-box {"active-box" if is_b else ""}">🎙️ Station B </div>', unsafe_allow_html=True)
        
        # Language Selection
        lang_b = st.selectbox("Language B", list(LANGS.keys()), index=list(LANGS.keys()).index(state.settings['speaker_b_lang']), format_func=lambda x: LANGS[x], key="sb_lang")
        if lang_b != state.settings['speaker_b_lang']:
            with state.lock:
                state.settings['speaker_b_lang'] = lang_b
                state.settings['speaker_b_locale'] = ACCENTS.get(lang_b, [lang_b])[0]
                state.live_caption = ""
                state.live_translation = ""

        # Accent Selection
        acc_options_b = ACCENTS.get(state.settings['speaker_b_lang'], [state.settings['speaker_b_lang']])
        try: acc_idx_b = acc_options_b.index(state.settings['speaker_b_locale'])
        except: acc_idx_b = 0
        acc_b = st.selectbox("Accent B", acc_options_b, index=acc_idx_b, key="sb_acc")
        if acc_b != state.settings['speaker_b_locale']:
            with state.lock: 
                state.settings['speaker_b_locale'] = acc_b
                state.live_caption = ""
                state.live_translation = ""
            
        if st.button("Activate Station B", disabled=is_b, use_container_width=True):
            with state.lock: state.settings['active_speaker'] = "B"
            flush_audio()

    st.subheader("📺 Continuous Subtitle Feed")
    if st.session_state.running:
        if state.error_msg:
            st.error(f"⚠️ {state.error_msg}")
        
        # Determine labels for transparency
        s = state.settings
        if s['active_speaker'] == "A":
            src_name, tgt_name = LANGS.get(s['speaker_a_lang'], "N/A"), LANGS.get(s['speaker_b_lang'], "N/A")
        else:
            src_name, tgt_name = LANGS.get(s['speaker_b_lang'], "N/A"), LANGS.get(s['speaker_a_lang'], "N/A")
            
        st.markdown(f'<div style="text-align:right; margin-bottom: -15px;"><span style="background:#00d4ff; color:#060709; padding:2px 10px; border-radius:15px; font-size:0.8em; font-weight:bold; position:relative; z-index:10;">{src_name} ➔ {tgt_name}</span></div>', unsafe_allow_html=True)
        
        st.markdown(f'<div class="caption-box"> <div style="font-size:1.4em;">{state.live_caption or "Waiting for voice..."}</div>'
                    f'<div style="color:#00d4ff; font-style:italic; font-size:1.2em;">{state.live_translation}</div> </div>', unsafe_allow_html=True)
    else: st.info("System Offline. Click Initiate Stream to start.")

    st.divider()
    with st.container(height=350):
        for h in state.history:
            st.markdown(f'<div style="padding:10px; border-bottom:1px solid rgba(255,255,255,0.05);">'
                        f'<small>{h["timestamp"]} | Station {h["speaker"]}</small><br>'
                        f'<b>{h["original"]}</b> → <span style="color:#00d4ff">{h["translated"]}</span></div>', unsafe_allow_html=True)



if __name__ == "__main__": 
    try:
        main()
    except Exception as e:
        import traceback
        st.error(f"App Crash: {str(e)}")
        st.code(traceback.format_exc())
        print(f"CRITICAL ERROR: {traceback.format_exc()}")
