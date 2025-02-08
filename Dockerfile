# Use an official lightweight Python image
FROM python:3.11-slim

# Install dependencies
RUN apt-get update 
RUN apt-get install -y ffmpeg 
# Keep image small
RUN rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy files
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the bot
CMD ["python", "main.py"]