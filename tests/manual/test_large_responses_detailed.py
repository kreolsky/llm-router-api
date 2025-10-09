#!/usr/bin/env python3
"""
Тест для проверки больших ответов с подробным логированием
Позволяет вручную проверить ответы модели и понять, почему тесты могут не проходить
"""

import asyncio
import sys
import httpx
import time
import json
from datetime import datetime

# Test configuration
BASE_URL = "http://localhost:8777"
API_KEY = "dummy"  # From config/user_keys.yaml
TEST_MODEL = "local/orange"  # Модель для тестирования

# ANSI color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"

def print_test(name: str):
    print(f"\n{BLUE}{'='*80}{RESET}")
    print(f"{BLUE}ТЕСТ: {name}{RESET}")
    print(f"{BLUE}{'='*80}{RESET}")

def print_success(msg: str):
    print(f"{GREEN}✓ {msg}{RESET}")

def print_error(msg: str):
    print(f"{RED}✗ {msg}{RESET}")

def print_warning(msg: str):
    print(f"{YELLOW}⚠ {msg}{RESET}")

def print_info(msg: str):
    print(f"{CYAN}ℹ {msg}{RESET}")

async def test_large_response_detailed(client: httpx.AsyncClient):
    """Тест большого ответа с подробным логированием"""
    print_test("Детальный тест большого ответа")
    
    payload = {
        "model": TEST_MODEL,
        "messages": [
            {"role": "user", "content": "Напиши подробное объяснение искусственного интеллекта. Включи следующие разделы:\n\n1. Введение в ИИ\n2. История развития\n3. Основные направления\n4. Современные приложения\n5. Будущее ИИ\n\nПостарайся дать максимально подробный ответ, чтобы я мог оценить качество работы системы."}
        ],
        "stream": True,
        "max_tokens": 1000
    }
    
    print_info(f"Отправка запроса: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    print_info(f"Модель: {payload['model']}")
    print_info(f"Длина сообщения: {len(payload['messages'][0]['content'])} символов")
    
    chunks_received = 0
    full_response = ""
    chunk_times = []
    start_time = time.time()
    
    try:
        async with client.stream(
            "POST",
            f"{BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=payload,
            timeout=60.0
        ) as response:
            print_info(f"Статус ответа: {response.status_code}")
            
            if response.status_code != 200:
                print_error(f"HTTP {response.status_code}")
                print_error(f"Текст ответа: {await response.aread()}")
                return False
            
            ttft_time = None
            first_chunk_time = None
            
            async for chunk in response.aiter_bytes():
                current_time = time.time()
                chunks_received += 1
                
                if chunks_received == 1:
                    ttft_time = current_time - start_time
                    first_chunk_time = current_time
                    print_info(f"TTFT (Time To First Token): {ttft_time*1000:.2f}ms")
                    print_info(f"Первый чанк получен: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
                
                chunk_elapsed = current_time - first_chunk_time if first_chunk_time else 0
                chunk_times.append(chunk_elapsed)
                
                decoded = chunk.decode('utf-8')
                
                # Проверка на ошибки
                if '"error"' in decoded:
                    print_error(f"Ошибка в стриме: {decoded}")
                    return False
                
                # Извлечение контента
                content_extracted = ""
                for line in decoded.split('\n'):
                    if line.startswith('data: ') and line != 'data: [DONE]':
                        try:
                            data = json.loads(line[6:])
                            if 'choices' in data and data['choices']:
                                content = data['choices'][0].get('delta', {}).get('content', '')
                                if content:
                                    content_extracted += content
                                    full_response += content
                        except json.JSONDecodeError:
                            pass
                
                if content_extracted:
                    print_info(f"Чанк {chunks_received}: +{len(content_extracted)} символов (всего: {len(full_response)})")
                    if len(full_response) <= 200:  # Показываем первые 200 символов
                        print_info(f"  Контент: '{full_response}'")
                else:
                    print_info(f"Чанк {chunks_received}: без контента")
            
            total_time = time.time() - start_time
            avg_chunk_time = sum(chunk_times) / len(chunk_times) if chunk_times else 0
            
            print_info(f"Тест завершен: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
            print_info(f"Общее время: {total_time:.2f}s")
            print_info(f"Получено чанков: {chunks_received}")
            print_info(f"Среднее время на чанк: {avg_chunk_time*1000:.2f}ms")
            print_info(f"Общий размер ответа: {len(full_response)} символов")
            print_info(f"TTFT: {ttft_time*1000:.2f}ms")
            
            # Детальный анализ ответа
            print_info(f"\n{'='*50} АНАЛИЗ ОТВЕТА {'='*50}")
            print_info(f"Полный ответ ({len(full_response)} символов):")
            print_info(f"'{full_response}'")
            
            if not full_response.strip():
                print_warning("Ответ пустой!")
                return False
            
            if len(full_response) < 100:
                print_warning("Ответ слишком короткий для большого запроса")
                return False
            
            print_success("Ответ получен и содержит данные")
            return True
            
    except Exception as e:
        print_error(f"Исключение: {e}")
        return False

async def test_multiple_requests(client: httpx.AsyncClient):
    """Тест нескольких запросов для проверки стабильности"""
    print_test("Тест нескольких запросов")
    
    requests = [
        {"model": TEST_MODEL, "content": "Кратко объясни, что такое ИИ", "max_tokens": 100},
        {"model": TEST_MODEL, "content": "Опиши основные принципы машинного обучения", "max_tokens": 150},
        {"model": TEST_MODEL, "content": "Что такое нейронные сети?", "max_tokens": 200},
    ]
    
    results = []
    
    for i, req in enumerate(requests):
        print_info(f"Запрос {i+1}/{len(requests)}: {req['content'][:50]}...")
        
        payload = {
            "model": req["model"],
            "messages": [{"role": "user", "content": req["content"]}],
            "stream": True,
            "max_tokens": req["max_tokens"]
        }
        
        start_time = time.time()
        chunks_received = 0
        full_response = ""
        
        try:
            async with client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=30.0
            ) as response:
                
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    results.append(False)
                    continue
                
                ttft = None
                async for chunk in response.aiter_bytes():
                    chunks_received += 1
                    if chunks_received == 1:
                        ttft = time.time() - start_time
                    
                    decoded = chunk.decode('utf-8')
                    for line in decoded.split('\n'):
                        if line.startswith('data: ') and line != 'data: [DONE]':
                            try:
                                data = json.loads(line[6:])
                                if 'choices' in data and data['choices']:
                                    content = data['choices'][0].get('delta', {}).get('content', '')
                                    if content:
                                        full_response += content
                            except:
                                pass
                
                total_time = time.time() - start_time
                print_info(f"  TTFT: {ttft*1000:.2f}ms, Чанков: {chunks_received}, Ответ: {len(full_response)} символов")
                
                if full_response.strip():
                    print_info(f"  Ответ: '{full_response}'")
                    results.append(True)
                else:
                    print_warning("  Пустой ответ")
                    results.append(False)
                    
        except Exception as e:
            print_error(f"  Исключение: {e}")
            results.append(False)
    
    success_count = sum(results)
    print_info(f"Успешных запросов: {success_count}/{len(requests)}")
    return success_count == len(requests)

async def main():
    print(f"\n{BLUE}{'='*80}{RESET}")
    print(f"{BLUE}ДЕТАЛЬНЫЙ ТЕСТ БОЛЬШИХ ОТВЕТОВ{RESET}")
    print(f"{BLUE}{'='*80}{RESET}")
    print(f"\nТестирование против: {BASE_URL}")
    print(f"API Key: {API_KEY}")
    
    async with httpx.AsyncClient() as client:
        results = {}
        
        # Запускаем тесты
        results["Большой ответ"] = await test_large_response_detailed(client)
        results["Множественные запросы"] = await test_multiple_requests(client)
        
        # Сводка
        print(f"\n{BLUE}{'='*80}{RESET}")
        print(f"{BLUE}РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ{RESET}")
        print(f"{BLUE}{'='*80}{RESET}")
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        for test_name, result in results.items():
            status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
            print(f"  {test_name:.<40} {status}")
        
        print(f"\n{BLUE}Итог: {passed}/{total} тестов passed{RESET}")
        
        if passed == total:
            print(f"{GREEN}✓ Все тесты пройдены!{RESET}\n")
            return 0
        else:
            print(f"{RED}✗ Некоторые тесты не пройдены. Проверьте логи выше.{RESET}\n")
            return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Тесты прерваны пользователем{RESET}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Фатальная ошибка: {e}{RESET}\n")
        sys.exit(1)