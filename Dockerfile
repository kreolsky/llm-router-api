# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install any needed packages specified in requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Run the application
# INVARIANT: one worker by default. SessionRegistry (stable ses_* ids), the
# capabilities cache and the SQLite usage writer are all process-local
# singletons, so extra workers fork them into independent copies. The
# gateway is I/O-bound (it awaits upstreams), so one worker is not the
# bottleneck. Raise API_WORKERS only after that state is moved out of process.
CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-1}"]
