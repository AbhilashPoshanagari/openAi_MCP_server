# Add these imports at the top of your voice_server.py
import av
import asyncio
from datetime import datetime
import json
import logging
import os
import uuid
import io
from typing import Dict, Optional
import wave

from aiortc.rtcpeerconnection import or_direction
import numpy as np

from fastapi.responses import JSONResponse
from starlette.routing import Route

from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCDataChannel,
    MediaStreamTrack
)

from aiortc.contrib.media import MediaRecorder

from av import AudioFrame
from pydub import AudioSegment

from openai import OpenAI

from thirdParty_apis.ibm_speech_to_text import IBMSpeechToTextHelper
import config

# Remove samplerate import as we'll use PyAV instead
# import samplerate

client = OpenAI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice_agent")

peer_connections: Dict[str, RTCPeerConnection] = {}

TARGET_SAMPLE_RATE = 16000

class AudioProcessorTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, track, pc):
        super().__init__()
        self.track = track
        self.pc = pc

        self.recording = False
        self.raw_frames = []
        self.frames = []
        
        # Replace samplerate resampler with PyAV AudioResampler
        # This resampler will convert incoming audio to 16kHz mono s16
        self.resampler = av.AudioResampler(
            format="s16",      # Output format: signed 16-bit
            layout="mono",     # Output layout: mono
            rate=TARGET_SAMPLE_RATE,  # Output rate: 16000 Hz
        )
        
        # Keep the resampler state between frames
        self._resampler_buffer = []
        
        self.gain_factor = 1.0
        self.clip_count = 0
        self._recording_lock = asyncio.Lock()  # Add lock for thread safety

    async def recv(self):
        frame = await self.track.recv()
        # Use lock to check recording state
        # async with self._recording_lock:
        #     is_recording = self.recording

        # if isinstance(frame, AudioFrame) and is_recording:
        #     await self.process_frame(frame)
        return frame
    
    async def process_frame(self, frame: AudioFrame):
        # Double-check recording state at start of processing
        async with self._recording_lock:
            if not self.recording:
                return
        
        # Quick check if audio has any non-zero values
        # Convert to numpy for checking (original frame might be in different format)
        pcm = frame.to_ndarray()
        # if np.any(pcm != 0):
        #     logger.info(f"!!! GOT NON-ZERO AUDIO !!! Shape: {pcm.shape}")
        #     non_zero_count = np.count_nonzero(pcm)
        #     logger.info(f"Non-zero samples: {non_zero_count}/{pcm.size}")
        # else:
        #     logger.warning("Received all-zero audio frame!")

        # logger.info(f"Original frame - Sample rate: {frame.sample_rate}, Format: {frame.format.name}, Layout: {frame.layout.name}")
        # logger.info(f"Frame shape: {pcm.shape}, dtype: {pcm.dtype}")

        # Store raw frame for debugging (before resampling)
        # Convert to float32 for raw storage (consistent with original behavior)
        if pcm.dtype == np.int16:
            pcm_float = pcm.astype(np.float32) / 32767.0
        elif pcm.dtype == np.int32:
            pcm_float = pcm.astype(np.float32) / 2147483647.0
        elif pcm.dtype == np.float32:
            pcm_float = pcm
        else:
            pcm_float = pcm.astype(np.float32)

        # Convert to mono for raw storage if needed
        if len(pcm_float.shape) > 1:
            if pcm_float.shape[0] == 2:  # channels first
                pcm_mono_raw = (pcm_float[0] + pcm_float[1]) / 2
            elif pcm_float.shape[1] == 2:  # channels last
                pcm_mono_raw = (pcm_float[:, 0] + pcm_float[:, 1]) / 2
            else:
                pcm_mono_raw = pcm_float.flatten()
        else:
            pcm_mono_raw = pcm_float
        
        pcm_mono_raw = pcm_mono_raw.flatten()
        
        # Store raw debug frames
        async with self._recording_lock:
            if self.recording:
                self.raw_frames.append(pcm_mono_raw.copy())

        # logger.info(f"Pre-resample levels - Min: {pcm_mono_raw.min():.4f}, Max: {pcm_mono_raw.max():.4f}, RMS: {np.sqrt(np.mean(pcm_mono_raw**2)):.4f}")

        # Use PyAV Resampler to convert to 16kHz mono s16
        try:
            # Resample the frame - resampler.resample returns a list of frames
            resampled_frames = self.resampler.resample(frame)
            
            for resampled_frame in resampled_frames:
                # Extract the audio data as int16 numpy array
                pcm16 = resampled_frame.to_ndarray()
                
                # Ensure it's 1D (mono) and contiguous
                if pcm16.ndim > 1:
                    pcm16 = pcm16.flatten()
                pcm16 = np.ascontiguousarray(pcm16, dtype=np.int16)
                
                # logger.info(f"Resampled frame - Shape: {pcm16.shape}, dtype: {pcm16.dtype}")
                # logger.info(f"Resampled Min/Max: {pcm16.min()}/{pcm16.max()}")
                
                # Calculate RMS from the int16 data
                rms = np.sqrt(np.mean((pcm16.astype(np.float32) / 32767.0) ** 2))
                # logger.info(f"Resampled RMS: {rms:.4f}")
                
                # Store the processed frame
                async with self._recording_lock:
                    if self.recording:
                        self.frames.append(pcm16)
                        
        except Exception as e:
            logger.error(f"Error during resampling: {e}")
            # Fallback to original method if resampling fails
            # logger.warning("Falling back to manual resampling")
            await self._fallback_process_frame(frame)

    async def _fallback_process_frame(self, frame: AudioFrame):
        """Fallback processing method if PyAV resampling fails"""
        pcm = frame.to_ndarray()
        
        # Convert to float32 with proper scaling
        if pcm.dtype == np.int16:
            pcm_float = pcm.astype(np.float32) / 32767.0
        elif pcm.dtype == np.int32:
            pcm_float = pcm.astype(np.float32) / 2147483647.0
        elif pcm.dtype == np.float32:
            pcm_float = pcm
        else:
            pcm_float = pcm.astype(np.float32)

        # Convert stereo to mono properly
        if len(pcm_float.shape) > 1:
            if pcm_float.shape[0] == 2:  # channels first
                pcm_mono = (pcm_float[0] + pcm_float[1]) / 2
            elif pcm_float.shape[1] == 2:  # channels last
                pcm_mono = (pcm_float[:, 0] + pcm_float[:, 1]) / 2
            else:
                pcm_mono = pcm_float.flatten()
        else:
            pcm_mono = pcm_float
        
        pcm_mono = pcm_mono.flatten()

        # Simple downsampling (just take every Nth sample - not ideal but works as fallback)
        sr_orig = frame.sample_rate
        if sr_orig != TARGET_SAMPLE_RATE:
            ratio = TARGET_SAMPLE_RATE / sr_orig
            # Very simple resampling - just decimation (only works for integer ratios)
            if ratio < 1 and sr_orig % TARGET_SAMPLE_RATE == 0:
                decimation = sr_orig // TARGET_SAMPLE_RATE
                pcm_mono = pcm_mono[::decimation]
        
        # Clip to prevent extreme values
        pcm_mono = np.clip(pcm_mono, -1.0, 1.0)
        
        # Convert to int16
        pcm16 = (pcm_mono * 32767).astype(np.int16)
        pcm16 = np.ascontiguousarray(pcm16)
        
        async with self._recording_lock:
            if self.recording:
                self.frames.append(pcm16)

    async def start_recording(self):
        async with self._recording_lock:
            # logger.info("Start recording")
            self.frames = []
            self.raw_frames = []
            self.recording = True
            # Reset the resampler buffer if needed
            self._resampler_buffer = []

    async def stop_recording(self):
        # First set recording to False to stop new frames
        async with self._recording_lock:
            # logger.info("Stop recording")
            self.recording = False
            # Create copies of the buffers
            frames_copy = self.frames.copy()
            raw_frames_copy = self.raw_frames.copy()
            # Clear the original buffers
            self.frames = []
            self.raw_frames = []
        
        # Process outside the lock to avoid blocking
        await self._process_recorded_audio(frames_copy, raw_frames_copy)

    async def _process_recorded_audio(self, frames_copy, raw_frames_copy):
        """Process the recorded audio after stopping"""
        if not frames_copy:
            logger.info("No audio captured")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Process raw audio (float32) - with normalization
        if raw_frames_copy:
            raw_audio = np.concatenate([f.flatten() for f in raw_frames_copy])
            
            # Normalize raw audio to prevent distortion
            max_val = np.max(np.abs(raw_audio))
            if max_val > 1.0:
                logger.info(f"Normalizing raw audio from max={max_val:.4f} to 1.0")
                raw_audio = raw_audio / max_val * 0.95  # Leave headroom
            elif max_val < 0.01:
                logger.info(f"Raw audio level is very low: max={max_val:.4f}")
            
            # Clip to safe range
            raw_audio = np.clip(raw_audio, -1.0, 1.0)
            
            # await self.save_audio_to_disk(
            #     raw_audio,
            #     sample_rate=48000,  # Assuming original was 48kHz
            #     channels=1,
            #     sample_width=4,
            #     filename=f"raw_webrtc_{timestamp}.wav"
            # )
            
            # Also save as int16 for comparison
            raw_int16 = (raw_audio * 32767).astype(np.int16)
            raw_int16 = np.ascontiguousarray(raw_int16)
            # await self.save_audio_to_disk(
            #     raw_int16,
            #     sample_rate=48000,
            #     channels=1,
            #     sample_width=2,
            #     filename=f"raw_int16_{timestamp}.wav"
            # )
        
        # Processed audio (already int16 from PyAV)
        if frames_copy:
            processed_audio = np.concatenate(frames_copy).astype(np.int16)
            processed_audio = np.ascontiguousarray(processed_audio)
            
            # Check for clipping in processed audio
            max_val = np.max(np.abs(processed_audio))
            if max_val > 32000:
                logger.warning(f"Processed audio near clipping: max={max_val}")
            
            logger.info(f"Processed audio - Min: {processed_audio.min()}, Max: {processed_audio.max()}")
            
            await self.save_audio_to_disk(
                processed_audio,
                sample_rate=TARGET_SAMPLE_RATE,
                channels=1,
                sample_width=2,
                filename=f"processed_16k_{timestamp}.wav"
            )
            
            # Send to STT
            audio_bytes = processed_audio.tobytes()
            
            # Add audio stats before sending
            audio_int16 = processed_audio.flatten()
            logger.info(f"Final audio stats - Min: {audio_int16.min()}, Max: {audio_int16.max()}, Mean: {audio_int16.mean():.2f}, RMS: {np.sqrt(np.mean(audio_int16.astype(np.float32)**2)):.2f}")
            
            await self.call_ibm_stt(audio_bytes)
    
    async def call_ibm_stt(self, audio_bytes):
        logger.info("Sending audio to IBM STT")

        headers = {
            "Content-Type": "audio/l16; rate=16000; channels=1"
        }

        response = IBMSpeechToTextHelper.post_request(
            url=f"{config.SPEECH_TO_TEXT_URL}/v1/recognize",
            audio_data=audio_bytes,
            apikey=config.SPEECH_TO_TEXT_APIKEY,
            headers=headers
        )

        logger.info(f"STT response : {response}")

        results = IBMSpeechToTextHelper.format_STT_response(response)

        text = results.get("transcript", "")

        logger.info(f"User said: {text}")

        await self.send_data({
            "type": "transcription",
            "text": text
        })
        # Get AI response if we have text
    #     if text:
    #         ai_text = await self.get_ai_response(text)
    #         await self.send_data({
    #             "type": "ai_response_text",
    #             "text": ai_text
    #         })

    # async def get_ai_response(self, text):
    #     try:
    #         response = await asyncio.to_thread(
    #             client.chat.completions.create,
    #             model="gpt-4o-mini",
    #             messages=[
    #                 {"role": "system", "content": "You are a helpful assistant"},
    #                 {"role": "user", "content": text}
    #             ]
    #         )
    #         return response.choices[0].message.content
    #     except Exception as e:
    #         logger.error(f"LLM error: {e}")
    #         return "Sorry, I couldn't process that."

    async def send_data(self, data):
        if hasattr(self.pc, "dc") and self.pc.dc:
            if self.pc.dc.readyState == "open":
                try:
                    self.pc.dc.send(json.dumps(data))
                except Exception as e:
                    logger.error(f"DataChannel error: {e}")

    async def save_audio_to_disk(self, audio_data, sample_rate, channels, sample_width, filename):
        try:
            os.makedirs("debug_audio", exist_ok=True)
            filepath = os.path.join("debug_audio", filename)
            
            # Validate audio data
            if isinstance(audio_data, np.ndarray):
                # Check for NaNs or Infs
                if np.any(np.isnan(audio_data)) or np.any(np.isinf(audio_data)):
                    logger.error("Audio contains NaN or Inf values!")
                    return None
                
                # Check for clipping
                if sample_width == 2:  # int16
                    max_val = np.max(np.abs(audio_data))
                    if max_val >= 32767:
                        logger.warning(f"Audio clipping detected! Max: {max_val}")
                
                audio_bytes = audio_data.tobytes()
            else:
                audio_bytes = audio_data
            
            # Write WAV file
            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_bytes)
            
            # logger.info(f"Saved debug audio → {filepath}")
            
            # Optional: Analyze the saved file
            if sample_width == 2 and channels == 1:
                audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
                logger.info(f"Audio stats - Min: {audio_int16.min()}, Max: {audio_int16.max()}, Mean: {audio_int16.mean():.2f}")
            
            return filepath
            
        except Exception as e:
            logger.error(f"Audio save error: {e}")
            return None

async def handle_offer(request):

    params = await request.json()

    offer = RTCSessionDescription(
        sdp=params["sdp"],
        type=params["type"]
    )

    pc = RTCPeerConnection()
    pc_id = str(uuid.uuid4())

    peer_connections[pc_id] = pc

    pc.dc = None
    pc.audio_processor = None


    @pc.on("datachannel")
    def on_datachannel(channel: RTCDataChannel):

        pc.dc = channel
        logger.info("DataChannel connected")

        @channel.on("message")
        async def on_message(message):

            try:

                data = json.loads(message)

                if data["type"] == "start":
                    await pc.audio_processor.start_recording()

                if data["type"] == "stop":
                    await pc.audio_processor.stop_recording()

            except Exception as e:
                logger.error(f"DataChannel message error: {e}")

    @pc.on("track")
    async def on_track(track):

        logger.info(f"Track received: {track.kind}")

        if track.kind == "audio":
            # Create processor that wraps the original track
            processor = AudioProcessorTrack(track, pc)
            pc.audio_processor = processor
            
            # Instead of replacing the track, we'll just consume it directly
            # Start a task to receive and process audio from this track
            asyncio.create_task(consume_audio_track(processor, track))
            
            logger.info("Started audio consumption task")

                
    @pc.on("connectionstatechange")
    async def on_state_change():
        logger.info(f"Connection state: {pc.connectionState}")
        if pc.connectionState in ["failed", "closed"]:
            # Use asyncio.create_task to avoid blocking the event handler
            asyncio.create_task(cleanup_pc(pc_id))

    await pc.setRemoteDescription(offer)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return JSONResponse({
        "data": {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type,
            "pc_id": pc_id
        }
    })

async def consume_audio_track(processor: AudioProcessorTrack, track: MediaStreamTrack):
    """Consume audio frames from the track and process them through the processor"""
    try:
        while True:
            # Receive frame from the original track
            frame = await track.recv()
            async with processor._recording_lock:
                is_recording = processor.recording

            # Let the processor handle it (it will check recording state internally)
            if isinstance(frame, AudioFrame)and is_recording:
                await processor.process_frame(frame)
                
    except asyncio.CancelledError:
        logger.info("Audio consumption task cancelled")
    except Exception as e:
        logger.error(f"Error consuming audio track: {e}")


async def add_ice_candidate(request):

    params = await request.json()

    pc_id = params["pc_id"]
    candidate = params["candidate"]

    pc = peer_connections.get(pc_id)

    if not pc:
        return JSONResponse({"error": "pc not found"}, status_code=404)

    await pc.addIceCandidate(candidate)

    return JSONResponse(content={"data": {"status": "ok"}}, status_code=200)


async def hangup(request):
    params = await request.json()
    pc_id = params.get("pc_id")  # Use .get() to avoid KeyError if pc_id is missing
    
    if not pc_id:
        return JSONResponse(content={"data": {"status": "error", "message": "pc_id required"}}, status_code=400)
    
    success = await cleanup_pc(pc_id)
    
    if success:
        return JSONResponse(content={"data": {"status": "ok"}}, status_code=200)
    else:
        return JSONResponse(content={"data": {"status": "not_found"}}, status_code=404)


async def cleanup_pc(pc_id):
    """Clean up peer connection. Returns True if found and cleaned, False otherwise."""
    pc = peer_connections.get(pc_id)
    
    if pc:
        try:
            # Close the connection
            await pc.close()
            
            # Remove from dictionary
            if pc_id in peer_connections:  # Double-check it's still there
                del peer_connections[pc_id]
                
            logger.info(f"Peer {pc_id} cleaned successfully")
            return True
        except Exception as e:
            logger.error(f"Error cleaning up peer {pc_id}: {e}")
            # Still try to remove from dictionary if it exists
            if pc_id in peer_connections:
                del peer_connections[pc_id]
            return False
    else:
        logger.warning(f"Peer {pc_id} not found for cleanup")
        return False


voice_media_routes = [
    Route('/offer', handle_offer, methods=['POST']),
    Route('/add_ice_candidate', add_ice_candidate, methods=['POST']),
    Route('/hangup', hangup, methods=['POST'])
]
