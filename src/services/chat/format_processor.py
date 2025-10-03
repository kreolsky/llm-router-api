"""
Преобразование форматов стриминга (SSE/NDJSON)
"""
import json
import time
from typing import Dict, Any, Tuple


class StreamFormatProcessor:
    """Преобразование форматов стриминга (SSE/NDJSON)"""
    
    def detect_format(self, data: str) -> str:
        """
        Определяет формат стриминга
        
        Args:
            data: Данные для анализа
            
        Returns:
            'sse' или 'ndjson'
        """
        if 'data:' in data or data.startswith(':'):
            return 'sse'
        else:
            return 'ndjson'
    
    def process_sse_event(self, event: str, full_content: str, usage: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Обрабатывает SSE событие
        
        Args:
            event: SSE событие
            full_content: Текущий полный контент
            usage: Текущие данные об использовании
            
        Returns:
            Tuple[updated_full_content, updated_usage]
        """
        for line in event.split('\n'):
            line = line.strip()
            
            # Пропускаем SSE комментарии
            if line.startswith(':'):
                continue
            
            if line.startswith('data: '):
                json_data = line[6:].strip()  # Удаляем 'data: ' префикс
                if json_data == '[DONE]':
                    continue
                    
                try:
                    data = json.loads(json_data)
                    
                    # Обработка ошибок в SSE данных
                    if 'error' in data:
                        continue
                    
                    # Извлечение контента
                    if 'choices' in data and len(data['choices']) > 0:
                        delta_content = data['choices'][0].get('delta', {}).get('content')
                        if delta_content:
                            full_content += delta_content
                    
                    # Извлечение данных об использовании
                    if 'usage' in data:
                        usage = data['usage']
                        
                except json.JSONDecodeError:
                    # Пропускаем невалидный JSON
                    pass
                    
        return full_content, usage
    
    def process_ndjson_line(self, line: str, model_id: str, request_id: str) -> Tuple[bytes, str, Dict[str, Any]]:
        """
        Обрабатывает NDJSON строку и возвращает OpenAI формат
        
        Args:
            line: NDJSON строка
            model_id: ID модели
            request_id: ID запроса
            
        Returns:
            Tuple[openai_chunk_bytes, content, usage]
        """
        processed_chunk = b""
        content = ""
        usage = {}
        
        try:
            data = json.loads(line)
            
            # Проверка завершения
            if data.get('done'):
                if 'prompt_eval_count' in data:
                    usage = {
                        "prompt_tokens": data.get("prompt_eval_count", 0),
                        "completion_tokens": data.get("eval_count", 0)
                    }
                elif 'usage' in data:
                    usage = data['usage']
                    
                return processed_chunk, content, usage
            
            # Извлечение контента
            delta_content = data.get('message', {}).get('content', '')
            if delta_content:
                content = delta_content
            
            # Формирование OpenAI совместимого чанка
            openai_chunk = {
                "id": f"chatcmpl-{request_id}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": delta_content},
                        "logprobs": None,
                        "finish_reason": None
                    }
                ]
            }
            
            processed_chunk = f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')
            
        except json.JSONDecodeError:
            # Возвращаем пустой результат при ошибке
            pass
            
        return processed_chunk, content, usage