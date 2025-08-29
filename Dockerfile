# Use a lightweight Python base
FROM python:3.11-slim

LABEL maintainer=""

# Set working directory inside container
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Run the main script
CMD ["python", "-u", "pvoutput.py"]
