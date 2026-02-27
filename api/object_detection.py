import av
import cv2
from fastapi import logger
from fastapi.responses import JSONResponse
from starlette.routing import Route
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRelay
import uuid
import logging

import torch
from ultralytics import YOLO

import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=1)

pcs = set()


# Load YOLOv5 model (or MobileNet)
class ObjectDetector:
    def __init__(self):
        # Load pre-trained YOLOv5 model
        # self.model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True)
        # self.model.eval()
        # self.model = YOLO("yolov5s.pt")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Using device: {self.device}")
        self.model = YOLO("yolov5nu.pt")
        self.model.to(self.device)
        self.confidence_threshold = 0.5
        
    def detect_objects(self, frame):
        # Convert frame to RGB
        # frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Run inference
        results = self.model(frame, verbose=False)
        
        # Process results
    # detections = results.pandas().xyxy[0]  # Get detection results
        result = results[0]
        # Boxes
        boxes = result.boxes

        if boxes is not None:
            for box in boxes:
                conf = float(box.conf[0])
                if conf < self.confidence_threshold:
                    continue

                # Get box coordinates
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                # Get class name
                cls_id = int(box.cls[0])
                label_name = self.model.names[cls_id]

                label = f"{label_name}: {conf:.2f}"

                # Draw bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    frame,
                    label,
                    (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    2,
                )
        
        return frame

# Initialize detector
detector = ObjectDetector()

class VideoTransformTrack(VideoStreamTrack):
    """
    A video stream track that applies object detection to video frames
    """
    def __init__(self, track):
        super().__init__()
        self.track = track
        self.counter = 0
        self.last_result = None
        self.loop = asyncio.get_event_loop()
        
    async def recv(self):
        frame = await self.track.recv()
        
        # Convert frame to numpy array for processing
        img = frame.to_ndarray(format="bgr24")
        self.counter += 1
        # Run inference every 2rd frame
        if self.counter % 5 == 0:
            # self.last_result = detector.detect_objects(img)
            self.last_result = await self.loop.run_in_executor(
                            executor,
                            detector.detect_objects,
                            img.copy()
                        )
        if self.last_result is not None:
            processed_img = self.last_result
        else:
            processed_img = img
        # Apply object detection
        # processed_img = detector.detect_objects(img)
        
        # Convert back to video frame
        new_frame = av.VideoFrame.from_ndarray(processed_img, format="bgr24")
        new_frame.pts = frame.pts
        new_frame.time_base = frame.time_base
        
        return new_frame

# class VideoTransformTrack(VideoStreamTrack):
#     """
#     A video stream track that receives frames and sends them back
#     without modification (or with future processing)
#     """
#     def __init__(self, track):
#         super().__init__()
#         self.track = track
#         self.counter = 0
        
#     async def recv(self):
#         # Receive the next video frame from the incoming track
#         frame = await self.track.recv()
#         self.counter += 1
        
#         # For now, just pass the frame through without modification
#         # Later you can add object detection here
        
#         # Log every 30 frames to avoid console spam
#         if self.counter % 30 == 0:
#             print(f"Processing frame {self.counter}")
        
#         return frame

async def offer(params: dict):
    """
    Handle WebRTC offer from client
    """
    data = await params.json()
    offer = RTCSessionDescription(sdp=data.get("sdp"), type=data.get("type"))
    pc = RTCPeerConnection()
    pc_id = f"peer-{uuid.uuid4()}"
    pcs.add(pc)

    pc.addTransceiver("video", direction="sendrecv")
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state for {pc_id}: {pc.connectionState}")
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
    
    @pc.on("track")
    async def on_track(track):
        print(f"Track received: {track.kind}")
        if track.kind == "video":
            # Apply object detection to incoming video stream
            local_track = VideoTransformTrack(track)
            print("Applying object detection to video track")
            # For demonstration, we will just relay the track without modification
            pc.addTrack(local_track)
            
            @track.on("ended")
            async def on_ended():
                print("Track ended")
    
    # Handle SDP offer
    await pc.setRemoteDescription(offer)
    
    # Create answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return JSONResponse(content={
        "data": {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
    }, status_code=200)

media_routes = [
    Route('/offer', offer, methods=['POST']),
]
