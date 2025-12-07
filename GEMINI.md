# GEMINI.md

## Project Overview

This project is a personal meme storage bot for Telegram. It allows users to send images (memes) to the bot, which then automatically extracts text from the images to use as tags. Users can later search for and retrieve their memes via Telegram's inline query mode using these tags.

The primary technologies used are:
- **Python**: The core application language.
- **python-telegram-bot**: The framework for interacting with the Telegram Bot API.
- **Docker & Docker Compose**: For containerizing and running the application services.
- **SQLite**: As the database for storing meme metadata.
- **PaddleOCR**: A library for Optical Character Recognition (OCR) to extract text from images for tagging.
- **GitHub Actions**: For continuous integration to build and push the Docker image to Docker Hub.

## Architecture

The application is composed of two main services, managed by `docker-compose.yml`:

1.  **`meme-storage-bot`**: This is the main service that runs the Telegram bot.
    - It listens for messages and commands from users.
    - When a photo is received, it saves the image to the `./memes` directory and a thumbnail to the `./thumbnails` directory.
    - It uses the PaddleOCR model in `src/ml.py` to analyze the image, extract Russian and English text, and generate tags.
    - It stores the meme's file path and tags in a SQLite database (`memes.db`).
    - It handles inline queries for searching memes by tags.

2.  **`http-server`**: This is a simple Python HTTP server that exposes the `memes/` and `thumbnails/` directories to the web.
    - This is necessary because Telegram's inline query results require a public URL for the photos and thumbnails.
    - This service is intended to be exposed to the internet, for example via a Cloudflare Tunnel, so Telegram's servers can access the images.

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

- **Database**: The application uses a SQLite database file located at `memes.db` in the project root. This file is mounted directly into the `meme-storage-bot` container at `/app/memes.db`.
- **Image and Thumbnail Storage**: Memes are stored in the `./memes` directory and thumbnails in `./thumbnails`. These are also mounted as volumes into the containers.
- **Bot Commands**:
  - `/start`: Shows a welcome message.
  - `/dump`: Dumps the database content to the chat.
  - `/clear`: Interactively asks for confirmation to clear the entire database.
  - `/regenerate_thumbnails`: Creates missing thumbnails for all memes in the database.
  - `/rescan`: Scans the `memes/` folder for images not present in the database, generates tags/thumbnails for them, and adds them.
- **CI/CD**: A GitHub Actions workflow in `.github/workflows/dockerhub.yaml` automatically builds the Docker image and pushes it to Docker Hub on every push to the `main` branch.
- **Dependencies**: Python dependencies are managed in `requirements.txt`. If you add a new dependency, be sure to add it to this file.
