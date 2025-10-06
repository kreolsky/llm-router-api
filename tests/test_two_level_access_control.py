import pytest
import httpx
from fastapi.testclient import TestClient
import os
import sys

# Добавляем путь к src в sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.api.main import app
from src.core.config_manager import ConfigManager

# Тестовые API ключи из конфигурации
TRANSCRIPTION_USER_KEY = "trans-key-789"
DEVELOPER_KEY = "dev-key-456"
EMBEDDING_USER_KEY = "embed-key-abc"
READONLY_USER_KEY = "ro-key-def"
ADMIN_KEY = "admin-key-123"  # Предполагаем, что такой ключ есть

BASE_URL = "http://localhost:8777"

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def audio_file():
    """Создает тестовый аудиофайл"""
    return ("test_audio.ogg", b"fake audio data", "audio/ogg")

class TestEndpointAccess:
    """Тесты для проверки доступа к endpoints"""
    
    def test_transcription_user_can_access_transcription_endpoint(self, client, audio_file):
        """Пользователь с доступом к транскрипции может обращаться к endpoint транскрипции"""
        response = client.post(
            f"{BASE_URL}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {TRANSCRIPTION_USER_KEY}"},
            files={"file": audio_file},
            data={"model": ""}  # Пустая модель для использования модели по умолчанию
        )
        # Ожидаем либо успешный ответ, либо ошибку провайдера, но не ошибку доступа
        assert response.status_code != 403
        assert response.status_code != 401
    
    def test_transcription_user_cannot_access_chat_endpoint(self, client):
        """Пользователь с доступом только к транскрипции не может обращаться к чату"""
        response = client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {TRANSCRIPTION_USER_KEY}"},
            json={"model": "test-model", "messages": [{"role": "user", "content": "test"}]}
        )
        assert response.status_code == 403
        assert "endpoint_not_allowed" in response.json()["error"]["code"]
    
    def test_transcription_user_cannot_access_embeddings_endpoint(self, client):
        """Пользователь с доступом только к транскрипции не может обращаться к embeddings"""
        response = client.post(
            f"{BASE_URL}/v1/embeddings",
            headers={"Authorization": f"Bearer {TRANSCRIPTION_USER_KEY}"},
            json={"model": "test-model", "input": "test"}
        )
        assert response.status_code == 403
        assert "endpoint_not_allowed" in response.json()["error"]["code"]
    
    def test_developer_can_access_chat_and_transcription(self, client, audio_file):
        """Разработчик может обращаться к чату и транскрипции"""
        # Проверка доступа к чату
        response = client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEVELOPER_KEY}"},
            json={"model": "deepseek/chat", "messages": [{"role": "user", "content": "test"}]}
        )
        # Ожидаем либо успешный ответ, либо ошибку модели, но не ошибку доступа
        assert response.status_code != 403
        assert response.status_code != 401
        
        # Проверка доступа к транскрипции
        response = client.post(
            f"{BASE_URL}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {DEVELOPER_KEY}"},
            files={"file": audio_file},
            data={"model": "stt/dummy"}
        )
        assert response.status_code != 403
        assert response.status_code != 401
    
    def test_developer_cannot_access_unallowed_model(self, client):
        """Разработчик не может использовать модели, не входящие в список разрешенных"""
        response = client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEVELOPER_KEY}"},
            json={"model": "gemini/pro", "messages": [{"role": "user", "content": "test"}]}
        )
        assert response.status_code == 403
        assert "model_not_allowed" in response.json()["error"]["code"]
    
    def test_embedding_user_can_only_access_embeddings(self, client):
        """Пользователь с доступом к embeddings может обращаться только к embeddings"""
        # Проверка доступа к embeddings
        response = client.post(
            f"{BASE_URL}/v1/embeddings",
            headers={"Authorization": f"Bearer {EMBEDDING_USER_KEY}"},
            json={"model": "embeddings/dummy", "input": "test"}
        )
        assert response.status_code != 403
        assert response.status_code != 401
        
        # Проверка отсутствия доступа к чату
        response = client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {EMBEDDING_USER_KEY}"},
            json={"model": "test-model", "messages": [{"role": "user", "content": "test"}]}
        )
        assert response.status_code == 403
        assert "endpoint_not_allowed" in response.json()["error"]["code"]
    
    def test_readonly_user_can_only_access_models_endpoints(self, client):
        """Пользователь только для чтения может обращаться только к endpoints моделей"""
        # Проверка доступа к списку моделей
        response = client.get(
            f"{BASE_URL}/v1/models",
            headers={"Authorization": f"Bearer {READONLY_USER_KEY}"}
        )
        assert response.status_code != 403
        assert response.status_code != 401
        
        # Проверка отсутствия доступа к чату
        response = client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {READONLY_USER_KEY}"},
            json={"model": "test-model", "messages": [{"role": "user", "content": "test"}]}
        )
        assert response.status_code == 403
        assert "endpoint_not_allowed" in response.json()["error"]["code"]
    
    def test_invalid_api_key(self, client):
        """Неверный API ключ должен возвращать ошибку 401"""
        response = client.get(
            f"{BASE_URL}/v1/models",
            headers={"Authorization": "Bearer invalid-key"}
        )
        assert response.status_code == 401
        assert "invalid_api_key" in response.json()["error"]["code"]
    
    def test_missing_api_key(self, client):
        """Отсутствующий API ключ должен возвращать ошибку 401"""
        response = client.get(f"{BASE_URL}/v1/models")
        assert response.status_code == 401
        assert "missing_api_key" in response.json()["error"]["code"]

class TestTranscriptionWithoutModel:
    """Тесты для проверки транскрипции без указания модели"""
    
    def test_transcription_without_model_with_allowed_user(self, client, audio_file):
        """Пользователь с доступом к транскрипции может отправлять запрос без модели"""
        response = client.post(
            f"{BASE_URL}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {TRANSCRIPTION_USER_KEY}"},
            files={"file": audio_file},
            data={}  # Не указываем модель
        )
        # Ожидаем либо успешный ответ, либо ошибку провайдера, но не ошибку доступа
        assert response.status_code != 403
        assert response.status_code != 401
    
    def test_transcription_without_model_with_developer(self, client, audio_file):
        """Разработчик может отправлять запрос транскрипции без модели"""
        response = client.post(
            f"{BASE_URL}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {DEVELOPER_KEY}"},
            files={"file": audio_file},
            data={}  # Не указываем модель
        )
        # Ожидаем либо успешный ответ, либо ошибку провайдера, но не ошибку доступа
        assert response.status_code != 403
        assert response.status_code != 401
    
    def test_transcription_with_empty_model(self, client, audio_file):
        """Проверка работы с пустой строкой в качестве модели"""
        response = client.post(
            f"{BASE_URL}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {TRANSCRIPTION_USER_KEY}"},
            files={"file": audio_file},
            data={"model": ""}  # Пустая строка
        )
        # Ожидаем либо успешный ответ, либо ошибку провайдера, но не ошибку доступа
        assert response.status_code != 403
        assert response.status_code != 401
    
    def test_transcription_with_specific_model_and_allowed_user(self, client, audio_file):
        """Пользователь с доступом ко всем моделям может использовать конкретную модель"""
        response = client.post(
            f"{BASE_URL}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {TRANSCRIPTION_USER_KEY}"},
            files={"file": audio_file},
            data={"model": "stt/dummy"}
        )
        # Ожидаем либо успешный ответ, либо ошибку провайдера, но не ошибку доступа
        assert response.status_code != 403
        assert response.status_code != 401
    
    def test_transcription_with_specific_model_and_restricted_user(self, client, audio_file):
        """Пользователь с ограниченным доступом не может использовать запрещенную модель"""
        # Предполагаем, что у пользователя developer нет доступа к модели, не входящей в его список
        response = client.post(
            f"{BASE_URL}/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {EMBEDDING_USER_KEY}"},  # У пользователя нет доступа к транскрипции
            files={"file": audio_file},
            data={"model": "stt/dummy"}
        )
        assert response.status_code == 403
        assert "endpoint_not_allowed" in response.json()["error"]["code"]

if __name__ == "__main__":
    pytest.main([__file__])