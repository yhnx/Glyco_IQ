import json
import time
import RPi.GPIO as GPIO
import subprocess
import os
import tflite_runtime.interpreter as tflite
import numpy as np
import cv2
from datetime import datetime

# Paths
BASE_DIR = "/home/yhnx/Documents/Data Collection"
IMAGE_DIR = os.path.join(BASE_DIR, "images")
os.makedirs(IMAGE_DIR, exist_ok=True)

# GPIO setup
LED_PIN = 18
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_PIN, GPIO.OUT)

# TFLite model setup
MODEL_PATH = "/home/yhnx/Documents/ann_model.tflite"
interpreter = tflite.Interpreter(model_path=MODEL_PATH)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

def compute_blue_histogram_features(image):
    """Compute blue channel histogram for TFLite model."""
    img_uint8 = (image * 255).astype(np.uint8)
    hist_b = cv2.calcHist([img_uint8], [2], None, [256], [0, 256]).flatten()  # Blue channel
    return hist_b / hist_b.sum()  # Normalize to unit sum

def preprocess_image(image_path):
    """Preprocess image for TFLite model (blue channel histogram)."""
    try:
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError("Failed to load image")
        
        # Resize to 640x480 (model's training resolution)
        img = cv2.resize(img, (640, 480))
        # Convert BGR to RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # Normalize to [0,1]
        img_normalized = img / 255.0
        # Compute blue channel histogram
        hist = compute_blue_histogram_features(img_normalized)
        # Reshape and convert to float32 for TFLite
        hist = hist.reshape(1, 256).astype(np.float32)
        return hist
    except Exception as e:
        print(f"Preprocessing error: {e}")
        return None

def capture_and_infer():
    """Capture image, run TFLite inference, and return result with 2 decimal places."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    image_filename = f"Glyco_{timestamp}.jpg"
    image_path = os.path.join(IMAGE_DIR, image_filename)
    temp_path = f"/tmp/temp_{timestamp}.jpg"

    try:
        # Turn on LED
        GPIO.output(LED_PIN, GPIO.HIGH)
        time.sleep(1)  # Allow stabilization

        # Capture image with libcamera-still (unchanged settings)
        subprocess.run([
            "libcamera-still",
            "-o", temp_path,
            "--width", "1280",
            "--height", "960",
            "--shutter", "100000",
            "--gain", "2",
            "--brightness", "0.2",
            "--contrast", "1.5",
            "--sharpness", "1.0",
            "--denoise", "cdn_off",
            "--awb", "auto",
            "--immediate",
            "--timeout", "100",
            "--nopreview"
        ], check=True)

        # Turn off LED
        GPIO.output(LED_PIN, GPIO.LOW)
        os.rename(temp_path, image_path)

        # Preprocess and run inference
        hist = preprocess_image(image_path)
        if hist is None:
            return {"status": "error", "message": "Image preprocessing failed"}

        interpreter.set_tensor(input_details[0]['index'], hist)
        interpreter.invoke()
        output_data = interpreter.get_tensor(output_details[0]['index'])
        prediction = float(output_data[0])  # Single output (glucose level in mmol/L)
        # Format to 2 decimal places
        prediction_formatted = float("{:.2f}".format(prediction))

        # Return result
        return {
            "status": "success",
            "glucose_level": prediction_formatted,
            "image_filename": image_filename
        }

    except subprocess.CalledProcessError:
        GPIO.output(LED_PIN, GPIO.LOW)
        return {"status": "error", "message": "Image capture failed"}
    except Exception as e:
        GPIO.output(LED_PIN, GPIO.LOW)
        return {"status": "error", "message": str(e)}
    finally:
        # Clean up temporary file if it exists
        if os.path.exists(temp_path):
            os.remove(temp_path)
        GPIO.cleanup()

# Main execution
if __name__ == "__main__":
    result = capture_and_infer()
    print(json.dumps(result))