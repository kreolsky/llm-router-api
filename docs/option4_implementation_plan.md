# Вариант 4: Передача флага завершения отдельно от данных

## Архитектура решения

Вместо создания служебных объектов типа `{'done': True}`, мы передаем флаг завершения как отдельное значение, возвращаемое из функций обработки.

## Детальная реализация

### Шаг 1: Изменение `_parse_sse_event`

```python
def _parse_sse_event(self, event_raw: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Парсит SSE событие и возвращает кортеж (данные, флаг_завершения)
    
    Returns:
        Tuple[Optional[Dict[str, Any]], bool]:
            - данные события или None
            - True если это событие завершения потока
    """
    if not event_raw.strip():
        return None, False
    
    try:
        for line in event_raw.split('\n'):
            line = line.strip()
            
            # Пропускаем комментарии
            if line.startswith(':'):
                continue
            
            # Проверяем на data: и ищем [DONE] в той же строке
            if line.startswith('data: ') and '[DONE]' in line:
                return None, True
            
            # Обычный data: с JSON
            if line.startswith('data: '):
                # Безопасное извлечение данных после 'data: '
                if ':' in line:
                    _, data_part = line.split(':', 1)
                    data_part = data_part.strip()
                    
                    # Дополнительная проверка на случай, если [DONE] не в начале
                    if data_part == '[DONE]':
                        return None, True
                    
                    # Парсим JSON
                    try:
                        return json.loads(data_part), False
                    except json.JSONDecodeError:
                        return None, False
        
        return None, False
    except Exception as e:
        logger.error(f"Error parsing SSE event: {e}", exc_info=True)
        return None, False
```

### Шаг 2: Изменение `_extract_sse_events`

```python
def _extract_sse_events(self, final: bool) -> List[Tuple[Dict[str, Any], bool]]:
    """
    Извлекает SSE события и возвращает список кортежей (данные, флаг_завершения)
    
    Returns:
        List[Tuple[Dict[str, Any], bool]]: Список событий с флагами завершения
    """
    events = []
    
    if not self.buffer:
        return events
    
    # Поддерживаем оба формата разделителей: \n\n и \r\n\r\n
    separator_positions = []
    
    # Ищем позиции всех возможных разделителей
    for separator in ['\r\n\r\n', '\n\n']:
        pos = self.buffer.find(separator)
        if pos != -1:
            separator_positions.append((pos, separator))
    
    # Сортируем по позиции (самый ранний разделитель)
    separator_positions.sort(key=lambda x: x[0])
    
    # Обрабатываем события пока есть разделители
    while separator_positions:
        pos, separator = separator_positions[0]
        event_raw = self.buffer[:pos]
        self.buffer = self.buffer[pos + len(separator):]
        
        event_data, is_done = self._parse_sse_event(event_raw)
        if event_data is not None or is_done:
            events.append((event_data, is_done))
        
        # Обновляем позиции для оставшегося буфера
        separator_positions = []
        for sep in ['\r\n\r\n', '\n\n']:
            pos = self.buffer.find(sep)
            if pos != -1:
                separator_positions.append((pos, sep))
        separator_positions.sort(key=lambda x: x[0])
    
    # Если final=True, обрабатываем оставшиеся данные
    if final and self.buffer.strip():
        event_data, is_done = self._parse_sse_event(self.buffer)
        if event_data is not None or is_done:
            events.append((event_data, is_done))
        self.buffer = ""
    
    return events
```

### Шаг 3: Изменение `_extract_ndjson_events`

```python
def _extract_ndjson_events(self, final: bool) -> List[Tuple[Dict[str, Any], bool]]:
    """
    Извлекает NDJSON события и возвращает список кортежей (данные, флаг_завершения)
    
    Returns:
        List[Tuple[Dict[str, Any], bool]]: Список событий с флагами завершения
    """
    events = []
    
    lines = self.buffer.split('\n')
    if not final:
        self.buffer = lines[-1]  # Сохраняем неполную строку
        lines = lines[:-1]
    else:
        self.buffer = ""
    
    for line in lines:
        if line.strip():
            try:
                event_data = json.loads(line)
                events.append((event_data, False))  # NDJSON не имеет специального маркера завершения
            except json.JSONDecodeError:
                continue
    
    return events
```

### Шаг 4: Изменение `_extract_events`

```python
def _extract_events(self, final: bool = False) -> List[Tuple[Dict[str, Any], bool]]:
    """
    Извлекает события из буфера и возвращает список кортежей (данные, флаг_завершения)
    
    Returns:
        List[Tuple[Dict[str, Any], bool]]: Список событий с флагами завершения
    """
    events = []
    
    if not self.buffer:
        return events
    
    # Определяем формат по первым данным
    stream_format = self._detect_format(self.buffer)
    
    if stream_format == 'sse':
        events = self._extract_sse_events(final)
    else:
        events = self._extract_ndjson_events(final)
    
    return events
```

### Шаг 5: Изменение основного метода `process_stream`

```python
async def process_stream(self,
                       provider_stream: AsyncGenerator[bytes, None],
                       model_id: str,
                       request_id: str,
                       user_id: str) -> AsyncGenerator[bytes, None]:
    """
    Main method for processing streaming responses.
    """
    logger.info("Starting stream processing", extra={
        "request_id": request_id,
        "user_id": user_id,
        "model": model_id
    })
    
    # Начинаем отсчет времени
    self.statistics.start_timing()
    
    full_content = ""
    stream_has_error = False
    first_token_received = False
    stream_ended = False
    
    try:
        event_count = 0
        async for chunk in provider_stream:
            try:
                # Декодируем и обрабатываем чанк
                decoded_chunk = self.utf8_decoder.decode(chunk, final=False)
                if decoded_chunk:
                    self.buffer += decoded_chunk
                    
                    # Обрабатываем события из буфера
                    events = self._extract_events()
                    for event_data, is_done in events:
                        event_count += 1
                        
                        # Если это событие завершения
                        if is_done:
                            stream_ended = True
                            break
                        
                        # Обрабатываем обычные данные
                        chunk_bytes = await self._process_event_data(
                            event_data, model_id, request_id, full_content
                        )
                        if chunk_bytes:
                            # Отмечаем получение первого токена
                            if not first_token_received:
                                first_token_received = True
                                self.statistics.mark_prompt_complete(0)
                            
                            yield chunk_bytes
                            # Обновляем контент для следующего события
                            full_content = self._extract_content(event_data, full_content)
                    
                    # Если поток завершен, выходим из цикла
                    if stream_ended:
                        break
            
            except Exception as e:
                logger.error("Stream processing error", extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "error": str(e),
                    "error_type": type(e).__name__
                }, exc_info=True)
                
                yield self._format_error(e)
                stream_has_error = True
                break
                
    except Exception as e:
        logger.error("Critical stream error", extra={
            "request_id": request_id,
            "user_id": user_id,
            "error": str(e)
        }, exc_info=True)
        
        yield self._format_error(e)
        stream_has_error = True
    
    # Завершаем стрим если не было ошибок
    if not stream_has_error:
        # Обрабатываем оставшиеся данные в буфере
        if self.buffer.strip():
            events = self._extract_events(final=True)
            for event_data, is_done in events:
                if is_done:
                    stream_ended = True
                    break
                
                chunk_bytes = await self._process_event_data(
                    event_data, model_id, request_id, full_content
                )
                if chunk_bytes:
                    yield chunk_bytes
                    full_content = self._extract_content(event_data, full_content)
        
        # Отмечаем завершение генерации и рассчитываем токены
        estimated_completion_tokens = self._estimate_tokens(full_content)
        self.statistics.mark_completion_complete(estimated_completion_tokens)
        
        # Отправляем финальное событие со статистикой
        statistics = self.statistics.get_statistics()
        if statistics:
            yield self._format_statistics_event(statistics, request_id, model_id)
        
        logger.info("Stream completed", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id,
            "content_length": len(full_content),
            "statistics": statistics
        })
        
        yield b"data: [DONE]\n\n"
    
    # Очищаем буфер
    self._clear_buffer()
```

## Преимущества этого подхода

1. **Чистота данных**: Никакие служебные поля не смешиваются с реальными данными сообщений
2. **Надежность**: Нет риска случайной отправки служебных полей провайдеру
3. **Архитектурная ясность**: Четкое разделение между данными и метаданными потока
4. **Гибкость**: Легко расширить для других типов флагов или метаданных
5. **Совместимость**: Полностью совместимо с существующим кодом обработки сообщений
6. **Устойчивость к изменениям формата**: Надежный парсинг без хрупких магических чисел

## Ключевые улучшения безопасности

1. **Проверка на `[DONE]` в строке**: Вместо хрупкого `line[6:]` используем `line.startswith('data: ') and '[DONE]' in line`
2. **Безопасное разделение**: `line.split(':', 1)` вместо жесткого смещения
3. **Двойная проверка**: Сначала проверяем на `[DONE]`, потом на JSON
4. **Защита от изменений формата**: Код устойчив к изменениям в формате `data: `

## Обратная совместимость

Этот подход не требует изменений на клиентской стороне и работает с существующими провайдерами. Все изменения происходят только внутри StreamProcessor.