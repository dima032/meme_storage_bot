# GEMINI.md

## Project Overview

This project is a personal meme storage bot for Telegram. It allows users to send images (memes) to the bot, which then automatically extracts text from the images to use as tags. Users can later search for and retrieve their memes via Telegram's inline query mode using these tags.

The primary technologies used are:
- **Python**: The core application language.
- **python-telegram-bot**: The framework for interacting with the Telegram Bot API.
- **Docker & Docker Compose**: For containerizing and running the application services.
- **SQLite**: As the database for storing meme metadata.
- **Hugging Face Transformers**: The `microsoft/Florence-2-large` model is used for Optical Character Recognition (OCR) to extract text from images for tagging.
- **FastAPI**: A modern, fast web framework for building APIs, used here to serve images securely.
- **GitHub Actions**: For continuous integration to build and push the Docker image to Docker Hub.

## Architecture

The application is composed of a single service defined in `docker-compose.yml` that runs the Telegram bot and the web server in the same container.

1.  **`meme-storage-bot`**: This is the main service that runs the Telegram bot and the FastAPI web server.
    - It listens for messages and commands from users.
    - When a photo is received, it saves the image to the `./memes` directory and a thumbnail to the `./thumbnails` directory.
    - It uses the `microsoft/Florence-2-large` model via the `transformers` library in `src/ml.py` to analyze the image and generate tags.
    - It stores the meme's file path and tags in a SQLite database (`memes.db`).
    - It handles inline queries for searching memes by tags.
    - It runs a `FastAPI` web server to expose the `memes/` and `thumbnails/` directories to the web. This is necessary because Telegram's inline query results require a public URL for the photos and thumbnails. The URLs are signed for security.

### Architecture Issues and Notes:
- **Redundant `http-server` Service**: The `docker-compose.yml` file defines a second service `http-server`. This service is redundant because the main `meme-storage-bot` service runs its own `FastAPI` web server which is properly configured for serving the meme files. The `http-server` service can be safely removed from `docker-compose.yml`.
- **Database Path Mismatch**: There is a bug in the volume mapping for the database. `docker-compose.yml` maps `./memes.db` to `/app/memes.db`, but `src/database.py` tries to connect to `/app/data/db/memes.db`. This will cause the database to be stored in the wrong location inside the container and it will not be persisted on the host. To fix this, the `volumes` section for the `meme-storage-bot` service in `docker-compose.yml` should be changed to:
  ```yaml
  volumes:
    - ./memes:/app/data/memes
    - ./thumbnails:/app/data/thumbnails
    - ./db:/app/data/db
  ```
  And you should create a `db` directory in your project root.
- **OCR Performance**: The `microsoft/Florence-2-large` model is a large and powerful model. Running it on a CPU is expected to be very slow. For better performance, a GPU is recommended. The model's performance on non-English languages like Russian may also vary.

## Building and Running

### Prerequisites
- Docker
- Docker Compose

### 1. Create the Environment File
The application requires an `.env` file with credentials and configuration. Create a file named `.env` in the project root by copying the example:

```bash
cp .env.example .env
```

Now, edit the `.env` file with your specific values:

- `TELEGRAM_TOKEN`: Your Telegram Bot API token, obtained from the BotFather.
- `PUBLIC_URL`: The public-facing URL where the `http-server` will be accessible (e.g., `https://your-tunnel.cloudflareapps.com`). **This must not have a trailing slash.**
- `ALLOWED_TELEGRAM_IDS`: A comma-separated list of numeric Telegram user IDs that are authorized to use this bot.
- `URL_SIGNING_SECRET`: A secret key for signing the image URLs. You can generate one with `openssl rand -hex 32`.
- `HUGGING_FACE_TOKEN` (Optional): Your Hugging Face Hub token, useful for other gated models.

### 2. Run with Docker Compose

Once the `.env` file is configured, you can build and run the application using Docker Compose:

```bash
docker-compose up --build -d
```
The `-d` flag will run the services in detached mode. To view logs, you can run:

```bash
docker-compose logs -f
```
### 3. Stopping the application
To stop the services, run:
```bash
docker-compose down
```
## Development Conventions

- **Database**: The application uses a SQLite database file located at `/app/data/db/memes.db` inside the container. See the note about the database path mismatch in the Architecture section.
- **Image and Thumbnail Storage**: Memes are stored in the `./memes` directory and thumbnails in `./thumbnails`. These are also mounted as volumes into the container.
- **Bot Commands**:
  - `/start`: Shows a welcome message.
  - `/dump`: Dumps the database content to the chat.
  - `/clear`: Interactively asks for confirmation to clear the entire database.
  - `/regenerate_thumbnails`: Creates missing thumbnails for all memes in the database.
  - `/rescan`: Scans the `memes/` folder for images not present in the database, generates tags/thumbnails for them, and adds them.
  - `/retag`: Re-runs the OCR process on all memes in the database to update their tags.
- **CI/CD**: A GitHub Actions workflow in `.github/workflows/dockerhub-main.yaml` automatically builds the Docker image and pushes it to Docker Hub on every push to the `main` branch.
- **Dependencies**: Python dependencies are managed in `requirements.txt`. If you add a new dependency, be sure to add it to this file.
