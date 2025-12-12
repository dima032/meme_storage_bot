import os
# Set a dummy username to prevent a bug in getpass.getuser() inside docker
os.environ['USER'] = 'app'

import re
import logging
import traceback
from transformers import AutoProcessor, AutoModelForCausalLM
from PIL import Image
import torch

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- OCR Component Initialization ---

# Initialize components to None by default
processor = None
model = None

# Get model and token from environment variables
model_name = "PaddlePaddle/PaddleOCR-VL"
hf_token = os.environ.get("HUGGING_FACE_TOKEN")

try:
    logger.info(f"Initializing OCR processor and model: {model_name}...")
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        token=hf_token,
        # load_in_8bit=True, # Temporarily disabled to check for memory issues
        device_map="auto",
        attn_implementation="eager",
        torch_dtype=torch.float16,
    )
    processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True, token=hf_token)
    logger.info("OCR components initialized successfully.")
except Exception as e:
    logger.error(f"Failed to initialize OCR components with model '{model_name}'. Error: {e}")
    logger.error(traceback.format_exc())
    processor = None
    model = None

# --- End of Initialization ---

def get_tags_for_image(image_path: str) -> list[str]:
    """
    Extracts text from an image using PaddleOCR-VL and returns a list of cleaned words (tags).
    """
    if not processor or not model:
        logger.error("OCR processor or model is not available. Cannot process image.")
        return []

    if not image_path:
        logger.warning("get_tags_for_image called with empty image_path.")
        return []

    try:
        logger.info(f"Processing image: {image_path}")
        image = Image.open(image_path).convert("RGB")

        # Prepare the prompt for PaddleOCR-VL
        messages = [{"role": "user", "content": f"<image>\nOCR"}]
        prompt_text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        inputs = processor(text=[prompt_text], images=[image], return_tensors="pt")
        inputs = {key: value.to(model.device, dtype=torch.float16 if value.dtype == torch.float32 else value.dtype) for key, value in inputs.items()}

        # Generate text
        with torch.inference_mode():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False,
                use_cache=True,
            )
        
        # Decode and parse the generated text
        response = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        # The response includes the prompt, so we split it to get only the answer
        text = response.split(prompt_text)[-1].strip()
        
        logger.info(f"Generated text: {text}")

        # Use regex to find all words that are at least 3 characters long
        words = re.findall(r'\b\w{3,}\b', text, re.UNICODE)

        # Clean up tags: lowercase and ensure they are unique
        tags = sorted(list(set([word.lower() for word in words])))

        logger.info(f"Found tags: {tags}")
        return tags

    except Exception as e:
        logger.error(f"Error processing image {image_path} with PaddleOCR-VL: {e}")
        logger.error(traceback.format_exc())
        return []

if __name__ == '__main__':
    # This test will now use Florence-2
    try:
        from PIL import Image, ImageDraw, ImageFont
        import os
        test_image_path = "test.png"
        if not os.path.exists(test_image_path):
            img = Image.new('RGB', (600, 150), color = (255, 255, 255))
            d = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("Arial.ttf", 30)
            except IOError:
                font = ImageFont.load_default()
            d.text((10,10), "This is a test of the\nFlorence-2 model.", fill=(0,0,0), font=font)
            img.save(test_image_path)
            print(f"Created a dummy test image: {test_image_path}")

        print("\n--- Running Test Case ---")
        # Ensure model is loaded for test
        if not model or not processor:
            print("Model not loaded, skipping test.")
        else:
            tags = get_tags_for_image(test_image_path)
            print(f"Tags extracted from {test_image_path}: {tags}")
            print("Expected (example): ['this', 'test', 'the', 'florence', 'model']")
        print("--- Test Case Finished ---\n")

    except Exception as e:
        print(f"An error occurred during the test run: {e}")
