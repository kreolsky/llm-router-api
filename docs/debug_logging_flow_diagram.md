# Диаграмма потока данных для DEBUG логирования

## Общая архитектура потока данных

```mermaid
graph TD
    A[Клиентский запрос] --> B[RequestLoggerMiddleware]
    B --> C[DEBUG: Логирование входящего JSON]
    C --> D[API Endpoint]
    D --> E[Сервисный слой]
    E --> F[DEBUG: Логирование в сервисе]
    F --> G[Провайдер]
    G --> H[DEBUG: Логирование запроса к провайдеру]
    H --> I[Внешний AI сервис]
    I --> J[Ответ от AI сервиса]
    J --> K[DEBUG: Логирование ответа от провайдера]
    K --> L[Обработка в сервисе]
    L --> M[DEBUG: Логирование ответа сервиса]
    M --> N[RequestLoggerMiddleware]
    N --> O[DEBUG: Логирование исходящего JSON]
    O --> P[Ответ клиенту]
    
    Q[LOG_LEVEL=DEBUG] --> C
    Q --> F
    Q --> H
    K --> Q
    M --> Q
    O --> Q
```

## Детальная диаграмма для Chat Service

```mermaid
sequenceDiagram
    participant Client as Клиент
    participant Middleware as RequestLoggerMiddleware
    participant ChatService as ChatService
    participant Provider as OpenAI Provider
    participant OpenAI as OpenAI API
    participant Logger as DEBUG Logger
    
    Client->>Middleware: POST /v1/chat/completions
    Middleware->>Logger: DEBUG: Incoming Request JSON
    Middleware->>ChatService: chat_completions(request, auth_data)
    
    ChatService->>Logger: DEBUG: Chat Completion Request JSON
    ChatService->>Provider: chat_completions(request_body, model_name, config)
    
    Provider->>Logger: DEBUG: OpenAI Chat Request
    Provider->>OpenAI: POST /chat/completions
    OpenAI->>Provider: Response JSON
    Provider->>Logger: DEBUG: OpenAI Chat Response
    Provider->>ChatService: response_data
    
    ChatService->>Logger: DEBUG: Chat Completion Response JSON
    ChatService->>Middleware: StreamingResponse/JSONResponse
    
    Middleware->>Logger: DEBUG: Outgoing Response JSON
    Middleware->>Client: Response
```

## Точки логирования в системе

```mermaid
graph LR
    subgraph "Точки входа"
        A1[Middleware - входящие запросы]
    end
    
    subgraph "Сервисный слой"
        B1[ChatService - запросы]
        B2[EmbeddingService - запросы]
        B3[TranscriptionService - запросы]
    end
    
    subgraph "Слой провайдеров"
        C1[BaseProvider - запросы к провайдерам]
        C2[OpenAI Provider - запросы]
        C3[Anthropic Provider - запросы]
        C4[Ollama Provider - запросы]
    end
    
    subgraph "Внешние сервисы"
        D1[OpenAI API]
        D2[Anthropic API]
        D3[Ollama API]
    end
    
    subgraph "Обратный поток"
        E1[BaseProvider - ответы от провайдеров]
        E2[OpenAI Provider - ответы]
        E3[Anthropic Provider - ответы]
        E4[Ollama Provider - ответы]
        
        F1[ChatService - ответы]
        F2[EmbeddingService - ответы]
        F3[TranscriptionService - ответы]
        
        G1[Middleware - исходящие ответы]
    end
    
    A1 --> B1
    A1 --> B2
    A1 --> B3
    
    B1 --> C1
    B2 --> C1
    B3 --> C1
    
    C1 --> C2
    C1 --> C3
    C1 --> C4
    
    C2 --> D1
    C3 --> D2
    C4 --> D3
    
    D1 --> E2
    D2 --> E3
    D3 --> E4
    
    E2 --> E1
    E3 --> E1
    E4 --> E1
    
    E1 --> F1
    E1 --> F2
    E1 --> F3
    
    F1 --> G1
    F2 --> G1
    F3 --> G1
```

## Структура DEBUG лога

```mermaid
graph TD
    A[DEBUG Log Entry] --> B[timestamp]
    A --> C[level: DEBUG]
    A --> D[message]
    A --> E[debug_json_data]
    A --> F[debug_data_flow]
    A --> G[debug_component]
    A --> H[request_id]
    
    E --> I[Полный JSON без изменений]
    F --> J[incoming/outgoing/to_provider/from_provider]
    G --> K[middleware/chat_service/provider/etc.]
    H --> L[Уникальный идентификатор запроса]
```

## Поток данных для стриминговых ответов

```mermaid
sequenceDiagram
    participant Client as Клиент
    participant ChatService as ChatService
    participant Provider as OpenAI Provider
    participant Logger as DEBUG Logger
    
    Client->>ChatService: Streaming Request
    ChatService->>Logger: DEBUG: Chat Completion Request JSON
    ChatService->>Provider: chat_completions(stream=true)
    Provider->>Logger: DEBUG: OpenAI Chat Request
    Provider-->>ChatService: StreamingResponse
    
    loop Потоковый ответ
        Provider->>ChatService: Chunk
        ChatService->>Logger: DEBUG: Streaming Chunk (первый chunk)
        ChatService->>Client: Processed Chunk
    end
    
    Note over Logger: Последующие chunks не логируются<br>для избежания избыточности
```

## Конфигурация и управление

```mermaid
graph TD
    A[LOG_LEVEL Environment Variable] --> B{LOG_LEVEL == DEBUG?}
    B -->|Да| C[Включить DEBUG логирование]
    B -->|Нет| D[Отключить DEBUG логирование]
    
    C --> E[Создать debug.log handler]
    C --> F[Логировать все JSON данные]
    
    D --> G[Только INFO/ERROR логи]
    D --> H[Минимальное влияние на производительность]
    
    E --> I[logs/debug.log файл]
    F --> I
    
    G --> J[logs/app.log файл]
    H --> J
```

## Использование для отладки

```mermaid
graph TD
    A[Редкий баг проявился] --> B[Включить LOG_LEVEL=DEBUG]
    B --> C[Воспроизвести запрос]
    C --> D[Найти request_id в логах]
    D --> E[grep по request_id]
    E --> F[Анализ полного потока данных]
    F --> G[Выявление проблемы]
    G --> H[Исправление]
    H --> I[Отключить DEBUG логирование]
    I --> J[LOG_LEVEL=INFO]