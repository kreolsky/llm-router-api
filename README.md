# LLM Router

## 🚀 Overview

A powerful and flexible proxy/router for Large Language Model (LLM) APIs, designed to streamline your application's interaction with various LLM providers. This project centralizes LLM access, allowing you to seamlessly integrate and manage diverse services like **DeepSeek, OpenRouter, OpenAI, and Ollama** from a single, unified endpoint. It offers features like intelligent model routing, dynamic configuration, robust authentication, detailed logging, and precise cost calculation, providing unparalleled flexibility in managing your LLM infrastructure.

## 💡 Why LLM Router?

In the rapidly evolving landscape of Large Language Models, managing multiple providers and ensuring consistent, cost-effective, and scalable access can be challenging. The NNP LLM Router addresses these complexities by offering:

*   **Simplified Integration:** Abstract away the complexities of different LLM APIs. Interact with all your models through a single, unified interface.
*   **Vendor Agnostic:** Avoid vendor lock-in. Easily switch between providers or integrate new ones without rewriting your application's core logic.
*   **Cost Optimization:** Centralized cost tracking and the ability to route requests to the most cost-effective models.
*   **Enhanced Control & Observability:** Gain granular control over model access, user permissions, and comprehensive insights into LLM usage patterns and costs.
*   **Scalability & Reliability:** Build a more robust and scalable LLM infrastructure by centralizing traffic and managing provider failovers.
*   **Future-Proofing:** Easily adapt to new LLM advancements and providers without significant architectural changes.

## ✨ Features

*   **Intelligent Routing:** Directs LLM requests to the provider based on your configuration.
*   **Multi-Provider Agnostic:** Seamlessly integrate with diverse LLM services (e.g., OpenAI, Anthropic).
*   **Dynamic Configuration:** Adjust providers, models, and API keys on the fly without service downtime.
*   **Secure Access:** Implement API key-based authentication and fine-grained model access control.
*   **Comprehensive Observability:** Detailed logging of requests, responses, token usage, and associated costs.
*   **Automated Cost Tracking:** Accurately calculates LLM usage expenses based on token consumption and pricing.

## 🌐 Supported LLM Providers

The NNP LLM Router is designed to be highly flexible and supports integration with a variety of Large Language Model (LLM) providers. Below is a list of currently supported and tested providers:

*   **DeepSeek**
*   **OpenRouter**
*   **OpenAI**
*   **Ollama** (Local instances supported, see configuration details below)

**Note on Anthropic:** While the router's architecture supports Anthropic, it has not been thoroughly tested.

## 🛠️ Quick Start with Docker Compose

This section guides you through setting up and running the NNP LLM Router using Docker Compose.

### Prerequisites

Ensure you have Docker and Docker Compose installed on your system.

### Configuration

Before running the router, you need to set up your configuration files and environment variables.

1.  **Configuration Files:**
    Create or modify the following files within the `config/` directory:
    *   `config/providers.yaml`: Define your LLM providers and their specific settings (e.g., API endpoints, types).
    *   `config/models.yaml`: Configure the LLM models, their mapping to providers, and any custom parameters.
    *   `config/user_keys.yaml`: Manage API keys for accessing the router and specify which models each key can use.

### Ollama Provider Specifics

The router supports integration with local Ollama instances. When configuring Ollama in `config/providers.yaml`, ensure the `base_url` is correctly set for your environment:

```yaml
 ollama:
   type: ollama
   base_url: http://192.168.1.52:11434/api # Replace with your Ollama instance's IP/hostname
```

2.  **Environment Variables:**
    Create a `.env` file in the root directory of this project. This file will store sensitive information like your LLM provider API keys.
    Example:
    ```
    OPENAI_API_KEY=your_openai_api_key_here
    ANTHROPIC_API_KEY=your_anthropic_api_key_here
    ```
    *Replace `your_openai_api_key_here` and `your_anthropic_api_key_here` with your actual API keys.*

### Running the Router

1.  Navigate to the root directory of this project in your terminal.
2.  Build and start the Docker containers:
    ```bash
    docker-compose up --build -d
    ```
    This command builds the necessary Docker images (if they don't exist or have changed) and starts the services in detached mode.

3.  The NNP LLM Router API will be accessible at `http://localhost:8777`.

### Health Check

Verify that the service is running correctly by accessing the health endpoint:
```
GET http://localhost:8777/health
```
A successful response indicates the router is operational.

## 🚀 Usage Examples

The NNP LLM Router acts as a central point for all your LLM interactions. Below are examples demonstrating how to use the `/v1/chat/completions` endpoint, which mimics the OpenAI Chat Completions API.

### Example 1: Basic Chat Completion

To get a simple chat completion, send a POST request to `/v1/chat/completions` with your desired model and messages.

```bash
curl -X POST http://localhost:8777/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_ROUTER_API_KEY" \
     -d '{
           "model": "your-configured-model-id",
           "messages": [
             {"role": "system", "content": "You are a helpful assistant."},
             {"role": "user", "content": "What is the capital of France?"}
           ]
         }'
```

*Replace `YOUR_ROUTER_API_KEY` with an API key configured in `config/user_keys.yaml` and `your-configured-model-id` with an ID from `config/models.yaml`.*

### Example 2: Streaming Responses

For real-time updates, you can enable streaming by adding `"stream": true` to your request.

```bash
curl -X POST http://localhost:8777/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_ROUTER_API_KEY" \
     -d '{
           "model": "your-configured-model-id",
           "messages": [
             {"role": "user", "content": "Tell me a long story about a space explorer."},
           ],
           "stream": true
         }'
```

### Example 3: Specifying Temperature and Max Tokens

You can also pass additional parameters like `temperature` and `max_tokens` to control the generation behavior.

```bash
curl -X POST http://localhost:8777/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_ROUTER_API_KEY" \
     -d '{
           "model": "your-configured-model-id",
           "messages": [
             {"role": "user", "content": "Write a short poem about nature."},
           ],
           "temperature": 0.7,
           "max_tokens": 50
         }'
```

### Example 4: Creating Embeddings

To generate embeddings for a given text, send a POST request to `/v1/embeddings`.

```bash
curl -X POST "http://localhost:8777/v1/embeddings" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_ROUTER_API_KEY" \
     -d '{
           "model": "embeddings/dummy",
           "input": "Hello, world!"
         }'
```
*Replace `YOUR_ROUTER_API_KEY` with an API key configured in `config/user_keys.yaml` and `embeddings/dummy` with your configured embeddings model ID.*

### Example 5: Creating Audio Transcriptions

To transcribe an audio file, send a POST request to `/v1/audio/transcriptions` with your audio file and the desired transcription model.

```bash
curl -X POST http://localhost:8777/v1/audio/transcriptions \
    -H "Content-Type: multipart/form-data" \
    -H "Authorization: Bearer YOUR_ROUTER_API_KEY" \
    -F "audio_file=@your_audio_file.ogg" \
    -F "model=transcriptions/dummy" \
    -F "response_format=json" \
    -F "temperature=0.0" \
    -F "language=en" \
    -F "return_timestamps=false"
```
*Replace `YOUR_ROUTER_API_KEY` with an API key configured in `config/user_keys.yaml`, `your_audio_file.ogg` with the path to your audio file, and `transcriptions/dummy` with your configured transcription model ID.*

## 🔗 API Endpoints

The router exposes a set of RESTful API endpoints for interaction:

*   `GET /health`: Checks the service health and readiness.
*   `GET /v1/models`: Retrieves a list of all configured LLM models.
*   `GET /v1/models/{model_id}`: Fetches detailed information for a specific model by its ID.
*   `POST /v1/chat/completions`: The primary endpoint for chat completion requests. It adheres to the standard OpenAI Chat Completions API request format and intelligently routes requests to the appropriate LLM provider.
*   `POST /v1/embeddings`: The endpoint for generating embeddings. It adheres to the standard OpenAI Embeddings API request format and routes requests to the configured embeddings provider.
*   `POST /v1/audio/transcriptions`: The endpoint for transcribing audio. It adheres to the standard OpenAI Audio Transcriptions API request format and routes requests to the configured transcription provider.
