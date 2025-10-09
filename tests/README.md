# NNP LLM Router Test Suite

This directory contains a comprehensive test suite for the NNP LLM Router API. The test suite is designed to validate all aspects of the API functionality, including connectivity, model enumeration, chat completions, embeddings, transcriptions, and endpoint permissions.

## Test Suite Structure

```
tests/
├── README.md                           # This file
├── conftest.py                         # Common fixtures and configuration
├── test_utils.py                       # Utility functions and classes
├── api/                                # API endpoint tests
│   ├── test_connectivity.py            # Connectivity tests
│   ├── test_models_endpoints.py        # Model enumeration tests
│   ├── test_chat_completions.py        # Chat completion tests
│   ├── test_embeddings.py              # Embedding tests
│   ├── test_transcriptions.py          # Transcription tests
│   └── test_endpoint_permissions.py    # Endpoint permissions tests
├── manual/                             # Manual tests
│   ├── test_hidden_models.py           # Hidden model access tests
│   ├── test_large_responses_detailed.py # Large response handling tests
│   ├── test_models.py                  # Model functionality tests
│   ├── test_smart_buffering_integration.py # Smart buffering tests
│   ├── test_streaming_fixes.py         # Streaming fixes tests
│   ├── test_streaming_models.py        # Streaming model tests
│   └── test_ttft_external.py           # Time to first token tests
└── transcription.ogg                   # Test audio file
```

## Quick Start

### Prerequisites

- Python 3.8 or higher
- pytest and pytest-asyncio
- httpx
- The NNP LLM Router API running on `http://localhost:8777`

### Installation

1. Install the required dependencies:
```bash
pip install pytest pytest-asyncio httpx numpy
```

2. Ensure the NNP LLM Router API is running on `http://localhost:8777`.

### Running Tests

1. Run all automated tests:
```bash
python -m pytest tests/api/ -v
```

2. Run specific test categories:
```bash
# Run connectivity tests
python -m pytest tests/api/test_connectivity.py

# Run model enumeration tests
python -m pytest tests/api/test_models_endpoints.py

# Run chat completion tests
python -m pytest tests/api/test_chat_completions.py

# Run embedding tests
python -m pytest tests/api/test_embeddings.py

# Run transcription tests
python -m pytest tests/api/test_transcriptions.py

# Run endpoint permissions tests
python -m pytest tests/api/test_endpoint_permissions.py
```

3. Run manual tests:
```bash
# Run hidden model tests
python -m pytest tests/manual/test_hidden_models.py

# Run streaming model tests
python -m pytest tests/manual/test_streaming_models.py

# Run TTFT tests
python -m pytest tests/manual/test_ttft_external.py
```

4. Run specific tests:
```bash
# Run a specific test
python -m pytest tests/api/test_chat_completions.py::TestChatCompletions::test_non_streaming_chat_completion

# Run tests with specific markers
python -m pytest -m "slow"
python -m pytest -m "integration"
python -m pytest -m "performance"
python -m pytest -m "streaming"
python -m pytest -m "auth"
```

## Test Configuration

The test suite can be configured using the following environment variables:

- `API_BASE_URL`: Base URL for the API (default: http://localhost:8777)
- `API_TIMEOUT`: Request timeout in seconds (default: 30)
- `MAX_RESPONSE_TIME`: Maximum allowed response time in seconds (default: 5.0)
- `MAX_TTFT`: Maximum allowed time to first token in seconds (default: 2.0)
- `MIN_THROUGHPUT`: Minimum required throughput in tokens/s (default: 0.5)

## Test Data

The test suite uses the following test data:

- **transcription.ogg**: Audio file for transcription tests
- **API keys**: Multiple API keys with different access levels
- **Test models**: Configuration for test models

## Test Categories

### 1. Automated API Tests

#### Connectivity Tests (`tests/api/test_connectivity.py`)
Validates basic API connectivity and service availability:
- Health check endpoint testing
- Service availability verification
- Docker setup verification
- Response time performance testing

#### Model Enumeration Tests (`tests/api/test_models_endpoints.py`)
Tests model listing and access control:
- List all models with different access levels
- Retrieve visible and hidden models by ID
- Model access with different authentication scenarios

#### Chat Completion Tests (`tests/api/test_chat_completions.py`)
Tests chat completion functionality for all test models:
- Non-streaming and streaming chat completions
- Chat completions with Unicode and emoji content
- Chat completions with various parameters
- Error handling for invalid models and missing fields

#### Embedding Tests (`tests/api/test_embeddings.py`)
Tests embedding functionality:
- Create embeddings for sample texts
- Create embeddings with different encoding formats
- Error handling for invalid models and missing fields

#### Transcription Tests (`tests/api/test_transcriptions.py`)
Tests audio transcription functionality:
- Create transcription for audio file
- Create transcription with different response formats
- Create transcription without specifying model
- Error handling for invalid models and missing fields

#### Endpoint Permissions Tests (`tests/api/test_endpoint_permissions.py`)
Tests endpoint-level permissions for different API keys:
- Full access key permissions for all endpoints
- Restricted access key permissions for specific endpoints
- Invalid key denial for all endpoints
- No authentication denial for all endpoints

### 2. Manual Tests

#### Hidden Model Tests (`tests/manual/test_hidden_models.py`)
Tests access to hidden models:
- Access to embeddings/dummy model
- Access to stt/dummy model
- Permission validation for hidden models

#### Large Response Tests (`tests/manual/test_large_responses_detailed.py`)
Tests handling of large responses:
- Large chat completion responses
- Memory usage during large responses
- Performance with large responses

#### Model Tests (`tests/manual/test_models.py`)
Tests model functionality:
- Model metadata validation
- Model configuration testing
- Model behavior verification

#### Smart Buffering Tests (`tests/manual/test_smart_buffering_integration.py`)
Tests smart buffering functionality:
- Buffer performance
- Buffer size optimization
- Buffer behavior under load

#### Streaming Fixes Tests (`tests/manual/test_streaming_fixes.py`)
Tests streaming fixes and improvements:
- Streaming format validation
- Streaming error handling
- Streaming performance optimization

#### Streaming Models Tests (`tests/manual/test_streaming_models.py`)
Tests streaming functionality for different models:
- Model-specific streaming behavior
- Streaming format compatibility
- Streaming performance by model

#### TTFT Tests (`tests/manual/test_ttft_external.py`)
Tests time to first token metrics:
- TTFT measurement for different models
- TTFT optimization validation
- TTFT performance under load

## Test Results

As of the latest test run, the test suite has the following results:
- **90+ passing tests**
- **15 failing tests** (primarily related to streaming format differences)
- **1 skipped test**

The failing tests are primarily related to differences between the expected OpenAI API format and the actual API implementation.

## Key Features

### 1. Comprehensive Endpoint Testing

The test suite covers all major API endpoints:
- Health check and connectivity
- Model enumeration
- Chat completions (streaming and non-streaming)
- Embeddings
- Audio transcriptions

### 2. Multi-Level Permission Testing

The test suite validates permissions at multiple levels:
- Endpoint-level permissions
- Model-level permissions
- API key-based access control

### 3. Special Case Testing

The test suite includes tests for special cases:
- Transcription without model specification
- Hidden model access
- Empty input handling
- Large file processing
- Unicode content handling

### 4. Performance and Concurrency Testing

The test suite includes performance and concurrency testing:
- Response time measurement
- Throughput calculation
- Concurrent request handling
- Memory usage monitoring

## Troubleshooting

### Common Issues

1. **Tests fail with connection errors**: Ensure the NNP LLM Router API is running on `http://localhost:8777`.
2. **Tests fail with timeout errors**: Increase the `API_TIMEOUT` environment variable.
3. **Tests fail with authentication errors**: Ensure the API keys in `conftest.py` are correct.

### Debugging

1. Run tests with verbose output:
```bash
python -m pytest tests/ -v
```

2. Run tests with detailed output:
```bash
python -m pytest tests/ -v -s
```

3. Run tests with specific output:
```bash
python -m pytest tests/ -v --tb=short
```

## Contributing

When adding new tests to the test suite:

1. Follow the existing test structure and naming conventions
2. Use the common fixtures and utility functions in `conftest.py` and `test_utils.py`
3. Add appropriate documentation for new tests

## Conclusion

The test suite provides a comprehensive foundation for testing the NNP LLM Router API. It covers all major functionality areas and is designed to be easily extended as the API evolves. The modular structure allows for easy maintenance and addition of new tests.