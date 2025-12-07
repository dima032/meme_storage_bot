FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p memes thumbnails

RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

# Change ownership of the app directory to the non-root user
RUN chown -R 1000:1000 /app

CMD ["python", "src/main.py"]
