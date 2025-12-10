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
# Note: Florence-2 is not gated, but we keep the token for other models.
model_name = "microsoft/Florence-2-large"
hf_token = os.environ.get("HUGGING_FACE_TOKEN")

try:
    logger.info(f"Initializing OCR processor and model: {model_name}...")
    # Florence-2 uses AutoModelForCausalLM and AutoProcessor
    # We add load_in_8bit=True to reduce memory usage and attn_implementation to avoid SDPA error.
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        token=hf_token,
        load_in_8bit=True,
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
    Extracts text from an image using Florence-2 and returns a list of cleaned words (tags).
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

        # Florence-2 requires a specific task prompt
        prompt = "<OCR>"

        # Process the image and prompt
        inputs = processor(text=prompt, images=image, return_tensors="pt")

        # Manually cast inputs to the correct dtype and device to match the model
        inputs = {key: value.to(model.device, dtype=torch.float16 if value.dtype == torch.float32 else value.dtype) for key, value in inputs.items()}

        # Generate text
        generated_ids = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=1024,
            use_cache=False,
        )
        
        # Decode the generated text
        generated_text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]

        # The model's output includes the prompt, so we need to parse it
        parsed_answer = processor.post_process_generation(generated_text, task="<OCR>", image_size=(image.width, image.height))
        
        # The parsed answer is a dict, e.g. {'<OCR>': 'text from image'}
        text = parsed_answer.get('<OCR>', '')
        logger.info(f"Generated text: {text}")

        # Use regex to find all words that are at least 3 characters long
        words = re.findall(r'\b\w{3,}\b', text, re.UNICODE)

        # Clean up tags: lowercase and ensure they are unique
        tags = sorted(list(set([word.lower() for word in words])))

        logger.info(f"Found tags: {tags}")
        return tags

    except Exception as e:
        logger.error(f"Error processing image {image_path} with Florence-2: {e}")
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
