## Live Language Translation

### Project Overview

Live Language Translation is a real-time, two-way speech translation system designed to remove language barriers during live conversations. It integrates cloud-based AI services with a reliable local processing engine to deliver fast, accurate, and natural translations. The application features a modern glassmorphic interface built with Streamlit, ensuring a clean, intuitive, and premium user experience.

---

## System Architecture: Inputs & Outputs

The system follows a structured pipeline that converts spoken language into translated speech with minimal delay.

### 1. Inputs (Data Ingestion)

#### Audio Input (Primary Source)

* **Type**: Continuous audio stream from microphone
* **Technology**: `SpeechRecognition` with dynamic energy thresholding
* **Purpose**: Distinguishes voice from background noise
* **Controls**: Adjustable sensitivity and noise calibration

#### User Configuration (UI Controls)

* **Language Selection**: Supports 50+ languages
* **Accent/Dialect**: Regional voice control (e.g., English US, English India)
* **Active Station Toggle**: Switch between Station A and Station B
* **Speech Rate**: Output voice speed from 0.5x to 2.0x

---

### 2. Processing Engine (Core Logic)

1. **Speech-to-Text (STT)**
   Converts spoken audio into text using Google Speech Recognition API.

2. **Text Normalization**
   Corrects phrases using a custom dictionary
   Example: `"chat gpt" → "ChatGPT"`

3. **Neural Translation**
   Translates normalized text using deep neural translation via `deep-translator`.

4. **Text-to-Speech (TTS)**
   Converts translated text into speech using Microsoft Edge Neural TTS (`edge-tts`).

---

### 3. Outputs (Deliverables)

#### Audio Output

* High-quality neural voice playback
* Played using `pygame` mixer
* Optimized for near real-time conversation

#### Visual Dashboard (Streamlit UI)

* **Live Captions**: Shows what the user is speaking
* **Live Translation**: Displays translated text instantly
* **Conversation History**:

  * Timestamped
  * Color-coded by Station A/B
  * Shows original and translated text

---

## Technical Stack

* **Frontend**: Streamlit
* **Audio Capture**: PyAudio, SpeechRecognition
* **Translation**: Google Translate via `deep-translator`
* **Text-to-Speech**: Microsoft Edge Neural TTS
* **Concurrency**: `threading` and `asyncio`

---

## Installation & Setup

### Prerequisites

* Python 3.8+
* Internet connection
* Microphone and speakers

### Installation

```bash
git clone <repository-url>
cd <repository-folder>
pip install -r requirements.txt
```

### Run the App

```bash
streamlit run transulator4_Pro.py
```

---

## Operation Guide

1. **Start the System**
   Launch the app and click **INITIATE STREAM**. Wait for the “Ready” status.

2. **Configure Languages**

   * Set Language and Accent for Station A
   * Set Language and Accent for Station B

3. **Start Conversation**

   * Click **Activate Station A** when Speaker A talks
   * System listens, translates, and speaks in Language B
   * Click **Activate Station B** when Speaker B replies

4. **Monitor Output**

   * Use Live Subtitle Feed to verify speech
   * Use History Log to review full conversation

---

Nova Transmit Pro delivers fast, natural, and reliable two-way translation—turning multilingual communication into a seamless experience.
