import os
import re
import logging
import easyocr
import torch

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- OCR Component Initialization ---

# Initialize components to None by default
reader = None

try:
    # Check if a GPU is available and initialize the reader accordingly
    gpu_available = torch.cuda.is_available()
    logger.info(f"Initializing EasyOCR reader. GPU available: {gpu_available}")
    # Initialize the OCR reader for Russian and English
    # This will download the models on the first run
    reader = easyocr.Reader(['ru', 'en'], gpu=gpu_available)
    logger.info("EasyOCR reader initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize EasyOCR reader. Error: {e}")
    reader = None

# --- End of Initialization ---

def get_tags_for_image(image_path: str) -> list[str]:
    """
    Extracts text from an image using EasyOCR and returns a list of cleaned words (tags).
    """
    if not reader:
        logger.error("EasyOCR reader is not available. Cannot process image.")
        return []

    if not image_path:
        logger.warning("get_tags_for_image called with empty image_path.")
        return []

    try:
        logger.info(f"Processing image with EasyOCR: {image_path}")
        
        # Read text from the image
        # The result is a list of tuples, where each tuple contains:
        # (bounding_box, recognized_text, confidence_score)
        results = reader.readtext(image_path)
        
        # Combine all recognized text fragments into a single string
        full_text = ' '.join([res[1] for res in results])
        
        logger.info(f"EasyOCR generated text: {full_text}")

        # Use regex to find all words that are at least 3 characters long
        words = re.findall(r'\b\w{3,}\b', full_text, re.UNICODE)

        # Clean up tags: lowercase and ensure they are unique
        tags = sorted(list(set([word.lower() for word in words])))

        logger.info(f"Found tags: {tags}")
        return tags

    except Exception as e:
        logger.error(f"Error processing image {image_path} with EasyOCR: {e}")
        return []