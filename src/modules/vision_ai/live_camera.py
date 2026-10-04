"""
Vision AI Step 7: Live Camera / Webcam Inference Script
======================================================
Beginner Explanation:
---------------------
How Live Edge Vision Works:
1. Opens a video capture stream (e.g., USB webcam on Pi 4 or CSI camera).
2. Reads frames in an infinite loop.
3. Downsamples to 320x320 for ultra-fast edge processing.
4. Passes each frame through our YOLO hazard model.
5. Draws bounding boxes, confidence badges, and real-time FPS overlay.
6. Emits warning if Fire or Smoke is detected.

Headless / No-Webcam Support:
If no physical webcam is plugged in, the script gracefully switches to
'Simulation / Video Loop' mode using sample images from the test dataset.
"""
import sys
import time
from pathlib import Path
import cv2
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parents[3]
MODEL_PATH = BASE_DIR / "models" / "vision" / "fire_smoke_best.pt"


def run_live_feed(camera_index: int = 0, conf_threshold: float = 0.35, max_frames: int = None):
    print("=" * 65)
    print("STEP 7: LIVE CAMERA / WEBCAM EDGE INFERENCE")
    print("=" * 65)

    weight_file = str(MODEL_PATH) if MODEL_PATH.exists() else "yolo11n.pt"
    print(f"Loading YOLO model: {weight_file}")
    model = YOLO(weight_file)

    # Attempt to open physical webcam
    print(f"Attempting to open camera device index: {camera_index}...")
    cap = cv2.VideoCapture(camera_index)

    simulated_mode = False
    test_images = []

    if not cap.isOpened():
        print("[INFO] Physical webcam not detected or accessible.")
        print("[INFO] Falling back to Simulated Urban Stream Mode using test dataset frames...")
        simulated_mode = True
        test_dir = BASE_DIR / "FIRE n SMOKE DETECTION.v1i.yolov11" / "test" / "images"
        test_images = list(test_dir.glob("*.jpg")) + list(test_dir.glob("*.png"))
        if not test_images:
            print("Error: No images found for simulation mode.")
            return

    frame_count = 0
    fps_display = 0.0
    prev_time = time.time()
    img_idx = 0

    print("\nStarting video stream loop. Press 'q' in video window to exit.")

    try:
        while True:
            if max_frames and frame_count >= max_frames:
                break

            if simulated_mode:
                img_path = test_images[img_idx % len(test_images)]
                frame = cv2.imread(str(img_path))
                img_idx += 1
                time.sleep(0.05)  # Simulate ~20 FPS frame rate
            else:
                ret, frame = cap.read()
                if not ret:
                    print("End of video stream or failed to grab frame.")
                    break

            frame_count += 1
            curr_time = time.time()
            fps_display = 1.0 / max(1e-5, (curr_time - prev_time))
            prev_time = curr_time

            # Run inference at 320x320
            results = model.predict(
                source=frame,
                imgsz=320,
                conf=conf_threshold,
                device="cpu",
                verbose=False
            )

            res = results[0]
            annotated_frame = res.plot()

            # Check if hazard detected
            num_detections = len(res.boxes)
            status_text = f"HAZARD DETECTED ({num_detections})" if num_detections > 0 else "STATUS: NORMAL"
            status_color = (0, 0, 255) if num_detections > 0 else (0, 255, 0)

            # Draw HUD Overlays
            cv2.rectangle(annotated_frame, (10, 10), (320, 80), (0, 0, 0), -1)
            cv2.putText(
                annotated_frame,
                f"FPS: {fps_display:.1f} | Res: 320x320",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 255),
                2
            )
            cv2.putText(
                annotated_frame,
                status_text,
                (20, 65),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                status_color,
                2
            )

            # Try to show GUI window if display is available
            try:
                cv2.imshow("Edge-AI Real-Time Vision Feed", annotated_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("User pressed 'q'. Exiting...")
                    break
            except Exception:
                # In headless environments cv2.imshow may raise error
                if frame_count % 10 == 0:
                    print(f"Processed frame {frame_count} | FPS: {fps_display:.1f} | {status_text}")
                if frame_count >= 30:  # Headless test run finishes after 30 frames
                    break

    except KeyboardInterrupt:
        print("\nStream stopped by user.")
    finally:
        if not simulated_mode:
            cap.release()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        print(f"[FINISHED] Processed {frame_count} frames. Average FPS: {fps_display:.1f}")


if __name__ == "__main__":
    # Test 10 frames in simulated mode to verify end-to-end execution
    run_live_feed(camera_index=0, max_frames=10)
