"""
Тесты для нового ChatService после рефакторинга
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from .src.core.config_manager import ConfigManager
from .src.services.chat_service_refactored import ChatService
from .src.services.model_service import ModelService


class TestChatServiceRefactored:
    """Тесты для рефакторингового ChatService"""
    
    @pytest.fixture
    def mock_config_manager(self):
        """Мок ConfigManager"""
        config = {
            "models": {
                "test/model": {
                    "provider": "test_provider",
                    "provider_model_name": "test-model"
                }
            },
            "providers": {
                "test_provider": {
                    "type": "openai",
                    "base_url": "https://api.test.com/v1",
                    "api_key_env": "TEST_API_KEY"
                }
            }
        }
        manager = Mock(spec=ConfigManager)
        manager.get_config.return_value = config
        return manager
    
    @pytest.fixture
    def mock_httpx_client(self):
        """Мок httpx клиента"""
        return Mock()
    
    @pytest.fixture
    def mock_model_service(self):
        """Мок ModelService"""
        return Mock(spec=ModelService)
    
    @pytest.fixture
    def chat_service(self, mock_config_manager, mock_httpx_client, mock_model_service):
        """ChatService с моками"""
        return ChatService(mock_config_manager, mock_httpx_client, mock_model_service)
    
    @pytest.fixture
    def mock_request(self):
        """Мок FastAPI запроса"""
        request = Mock(spec=Request)
        request.json = AsyncMock()
        request.state.request_id = "test-request-id"
        return request
    
    @pytest.fixture
    def auth_data(self):
        """Данные аутентификации"""
        return ("test_project", "test_api_key", ["test/model"])
    
    @pytest.fixture
    def request_body(self):
        """Тело запроса"""
        return {
            "model": "test/model",
            "messages": [{"role": "user", "content": "Hello"}]
        }
    
    @pytest.fixture
    def mock_provider_instance(self):
        """Мок провайдера"""
        provider = Mock()
        provider.chat_completions = AsyncMock()
        return provider
    
    @pytest.fixture
    def mock_non_streaming_response(self):
        """Мок нестримингового ответа"""
        return {"choices": [{"message": {"content": "Hello!"}}]}
    
    @pytest.fixture
    def mock_streaming_response(self):
        """Мок стримингового ответа"""
        streaming_response = Mock(spec=StreamingResponse)
        streaming_response.media_type = "text/event-stream"
        
        # Создаем асинхронный итератор
        async def mock_body_iterator():
            yield b'{"choices": [{"delta": {"content": "Hello"}}]}'
            yield b'{"choices": [{"delta": {"content": " World"}}]}'
            yield b'data: [DONE]\n\n'
        
        streaming_response.body_iterator = mock_body_iterator()
        return streaming_response
    
    @patch('src.services.chat_service_refactored.get_provider_instance')
    def test_chat_completions_non_streaming(
        self, 
        mock_get_provider,
        chat_service,
        mock_request,
        auth_data,
        request_body,
        mock_provider_instance,
        mock_non_streaming_response
    ):
        """Тест обработки нестримингового запроса"""
        # Настройка моков
        mock_request.json.return_value = request_body
        mock_get_provider.return_value = mock_provider_instance
        mock_provider_instance.chat_completions.return_value = mock_non_streaming_response
        
        # Вызов метода
        result = chat_service.chat_completions(mock_request, auth_data)
        
        # Проверки
        assert isinstance(result, JSONResponse)
        mock_provider_instance.chat_completions.assert_called_once_with(
            request_body, "test-model", chat_service.validator.config_manager.get_config()["models"]["test/model"]
        )
    
    @patch('src.services.chat_service_refactored.get_provider_instance')
    def test_chat_completions_streaming(
        self,
        mock_get_provider,
        chat_service,
        mock_request,
        auth_data,
        request_body,
        mock_provider_instance,
        mock_streaming_response
    ):
        """Тест обработки стримингового запроса"""
        # Настройка моков
        mock_request.json.return_value = request_body
        mock_get_provider.return_value = mock_provider_instance
        mock_provider_instance.chat_completions.return_value = mock_streaming_response
        
        # Вызов метода
        result = chat_service.chat_completions(mock_request, auth_data)
        
        # Проверки
        assert isinstance(result, StreamingResponse)
        mock_provider_instance.chat_completions.assert_called_once_with(
            request_body, "test-model", chat_service.validator.config_manager.get_config()["models"]["test/model"]
        )
    
    @patch('src.services.chat_service_refactored.get_provider_instance')
    def test_chat_completions_provider_error(
        self,
        mock_get_provider,
        chat_service,
        mock_request,
        auth_data,
        request_body,
        mock_provider_instance
    ):
        """Тест обработки ошибки провайдера"""
        # Настройка моков
        mock_request.json.return_value = request_body
        mock_get_provider.return_value = mock_provider_instance
        mock_provider_instance.chat_completions.side_effect = Exception("Provider error")
        
        # Вызов метода и проверка исключения
        with pytest.raises(HTTPException) as exc_info:
            chat_service.chat_completions(mock_request, auth_data)
        
        assert exc_info.value.status_code == 500
        assert "unexpected_error" in exc_info.value.detail["error"]["code"]
    
    @patch('src.services.chat_service_refactored.get_provider_instance')
    def test_chat_completions_invalid_model(
        self,
        mock_get_provider,
        chat_service,
        mock_request,
        auth_data,
        request_body
    ):
        """Тест обработки запроса с недопустимой моделью"""
        # Настройка моков
        mock_request.json.return_value = request_body
        auth_data = ("test_project", "test_api_key", ["other/model"])  # Другая модель
        
        # Вызов метода и проверка исключения
        with pytest.raises(HTTPException) as exc_info:
            chat_service.chat_completions(mock_request, auth_data)
        
        assert exc_info.value.status_code == 403
        assert "model_not_allowed" in exc_info.value.detail["error"]["code"]
    
    @patch('src.services.chat_service_refactored.get_provider_instance')
    def test_chat_completions_provider_config_error(
        self,
        mock_get_provider,
        chat_service,
        mock_request,
        auth_data,
        request_body
    ):
        """Тест ошибки конфигурации провайдера"""
        # Настройка моков
        mock_request.json.return_value = request_body
        mock_get_provider.side_effect = ValueError("Invalid provider configuration")
        
        # Вызов метода и проверка исключения
        with pytest.raises(HTTPException) as exc_info:
            chat_service.chat_completions(mock_request, auth_data)
        
        assert exc_info.value.status_code == 500
        assert "provider_config_error" in exc_info.value.detail["error"]["code"]
    
    def test_chat_service_initialization(self, mock_config_manager, mock_httpx_client, mock_model_service):
        """Тест инициализации ChatService"""
        service = ChatService(mock_config_manager, mock_httpx_client, mock_model_service)
        
        # Проверка инициализации компонентов
        assert service.config_manager == mock_config_manager
        assert service.httpx_client == mock_httpx_client
        assert service.model_service == mock_model_service
        assert service.validator is not None
        assert service.buffer_manager is not None
        assert service.format_processor is not None
        assert service.error_handler is not None
        assert service.logger is not None
        assert service.streaming_handler is not None
    
    def test_chat_service_components_dependency_injection(self, mock_config_manager, mock_httpx_client, mock_model_service):
        """Тест правильной инъекции зависимостей в компоненты"""
        service = ChatService(mock_config_manager, mock_httpx_client, mock_model_service)
        
        # Проверка, что компоненты правильно инициализированы
        assert service.validator.config_manager == mock_config_manager
        assert service.streaming_handler.buffer_manager == service.buffer_manager
        assert service.streaming_handler.format_processor == service.format_processor
        assert service.streaming_handler.error_handler == service.error_handler
        assert service.streaming_handler.logger == service.logger