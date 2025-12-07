import logging
import pytesseract
import cv2

# --- Initialize logging ---
logger = logging.getLogger(__name__)

# --- Define Stop Words ---
STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "of", "at", "by", "for", "with", "about", "against", "between",
    "into", "through", "during", "before", "after", "above", "below",
    "to", "from", "up", "down", "in", "out", "on", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "any", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "s", "t", "can", "will", "just", "don",
    "should", "now", "d", "ll", "m", "o", "re", "ve", "y", "ain", "aren",
    "couldn", "didn", "doesn", "hadn", "hasn", "haven", "isn", "ma",
    "mightn", "mustn", "needn", "shan", "shouldn", "wasn", "weren", "won",
    "wouldn"
}

# --- Main Tagging Function ---
def get_tags(image_path):
    """
    Extracts text from an image using Tesseract OCR, cleans it, and returns a list of tags.
    """
    logger.info(f"--- Starting tag generation with Tesseract for {image_path} ---")
    tags = set()
    
    try:
        # --- Image Pre-processing Pipeline ---
        image = cv2.imread(image_path)
        
        # 1. Convert to grayscale
        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # 2. Apply adaptive thresholding to get a clean binary image
        binary_image = cv2.adaptiveThreshold(
            gray_image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # --- Tesseract Configuration ---
        # --oem 3: Default OCR Engine Mode
        # --psm 6: Assume a single uniform block of text (good for memes)
        custom_config = r'--oem 3 --psm 6'

        # Use Tesseract to do OCR on the pre-processed image
        logger.info(f"Starting Tesseract text recognition for image: {image_path}...")
        extracted_text = pytesseract.image_to_string(binary_image, lang='eng+rus', config=custom_config)
        logger.info(f"Tesseract raw output: {extracted_text}")

        if extracted_text:
            words = extracted_text.split()
            for word in words:
                clean_word = ''.join(filter(str.isalnum, word)).lower()
                if len(clean_word) > 2 and clean_word not in STOP_WORDS:
                    tags.add(clean_word)

    except Exception as e:
        logger.error(f"Error during Tesseract OCR processing: {e}", exc_info=True)

    logger.info(f"--- Finished tag generation. Tags: {list(tags)} ---")
    return list(tags)

if __name__ == '__main__':
    # Example usage for testing
    try:
        test_tags = get_tags('test_image.png')
        print(f"Tags found: {test_tags}")
    except Exception as e:
        print(f"Could not process test_image.png. Error: {e}")
