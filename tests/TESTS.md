# Service Verification Steps

This document outlines the steps to verify the functionality of the `nnp-llm-router` service, including the newly added Ollama provider support.

## Prerequisites

*   Docker and Docker Compose installed and running.
*   Python 3.x and `pip` installed.
*   Necessary Python dependencies for testing installed (currently `httpx`: `pip install httpx`).

## Steps to Verify the Service

1.  **Start the Service in Docker:**
    Open your terminal in the project's root directory (`/Users/serge/Develop/nnp-llm-router`) and run the following command to start the service in a Docker container in detached mode:
    ```bash
    docker compose up -d
    ```
    This will build the Docker image (if not already built) and start the `api` service.

2.  **Run Tests from the Base Environment:**
    While the Docker service is running, execute the existing test suite from your local Python environment. These tests verify the core functionalities of the service.
    ```bash
    python tests/test_models.py
    ```
    You should see output indicating that various API endpoints were tested successfully, including model listing, model retrieval, and transcription (if configured).

    Additionally, run the tests for hidden models:
    ```bash
    python tests/test_hidden_models.py
    ```
    This test verifies that models marked as `is_hidden: true` are correctly excluded from the `/v1/models` list but are still accessible via `/v1/models/{model_id}`.

    *   **Verify Embedding Model Functionality:**
        This test ensures that even hidden embedding models function correctly when explicitly called.

3.  **Verify Ollama Integration (Manual Check - Optional):**
    To manually verify the Ollama integration, you would need an Ollama instance running locally (e.g., `ollama run llama2`). Once Ollama is running, you can send a request to your `nnp-llm-router` service using one of the configured Ollama models (e.g., `ollama/llama2`).

    Example `curl` command (replace `YOUR_API_KEY` with a valid key from `config/user_keys.yaml`):
    ```bash
    curl -X POST http://localhost:8777/v1/chat/completions \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer YOUR_API_KEY" \
      -d '{
        "model": "ollama/llama2",
        "messages": [
          {"role": "user", "content": "Hello, how are you?"}
        ]
      }'
    ```
    You should receive a response from your local Ollama instance via the `nnp-llm-router`.

    **Note on API Keys:** For testing purposes, you can find valid API keys in the `config/user_keys.yaml` file.

4.  **Review Test Results:**
    After running the tests, carefully review the output to ensure that all tests passed and the results meet your expectations. If the tests indicate any failures or unexpected behavior, investigate and resolve them before proceeding.

5.  **Stop the Docker Service:**
    Once you have finished verification and confirmed that all tests are successful, you can stop and remove the Docker containers by running:
    ```bash
    docker compose down