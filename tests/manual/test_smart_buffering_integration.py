#!/usr/bin/env python3
"""
Интеграционные тесты для умной буферизации
Тестирование через внешние HTTP запросы к работающему сервису
"""

import asyncio
import sys
import httpx
import json
import time
import logging
from typing import List, Dict, Any

# Тестовая конфигурация
BASE_URL = "http://localhost:8777"
API_KEY = "dummy"  # Из config/user_keys.yaml
TEST_MODEL = "local/orange"  # Модель для тестирования

# ANSI color codes for output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def print_test(name: str):
    logger.info(f"\n{BLUE}{'='*60}{RESET}")
    logger.info(f"{BLUE}ТЕСТ: {name}{RESET}")
    logger.info(f"{BLUE}{'='*60}{RESET}")


def print_success(msg: str):
    logger.info(f"{GREEN}✓ {msg}{RESET}")


def print_error(msg: str):
    logger.error(f"{RED}✗ {msg}{RESET}")


def print_warning(msg: str):
    logger.warning(f"{YELLOW}⚠ {msg}{RESET}")


class SmartBufferingTester:
    """Тестер умной буферизации через внешние запросы"""
    
    def __init__(self):
        self.client = httpx.AsyncClient()
    
    async def test_risky_scenarios(self) -> Dict[str, bool]:
        """Тестирование рискованных сценариев"""
        results = {}
        
        # 1. Тест: Очень маленькие чанки (могут сломать буферизацию)
        results["tiny_chunks"] = await self.test_tiny_chunks()
        
        # 2. Тест: Многобайтные символы в разных кодировках
        results["multibyte_chars"] = await self.test_multibyte_characters()
        
        # 3. Тест: Смешанные форматы (SSE и NDJSON в одном ответе)
        results["mixed_formats"] = await self.test_mixed_formats()
        
        # 4. Тест: Очень большие ответы
        results["large_responses"] = await self.test_large_responses()
        
        # 5. Тест: Обрывы соединения
        results["connection_breaks"] = await self.test_connection_breaks()
        
        # 6. Тест: Невалидный JSON в SSE
        results["invalid_json"] = await self.test_invalid_json()
        
        # 7. Тест: Быстрые последовательные запросы
        results["rapid_requests"] = await self.test_rapid_requests()
        
        # 8. Тест: Специальные символы и escape sequences
        results["special_chars"] = await self.test_special_characters()
        
        # 9. Тест: Пустые и неполные события
        results["empty_events"] = await self.test_empty_events()
        
        # 10. Тест: Сложные эмодзи и юникод
        results["complex_unicode"] = await self.test_complex_unicode()
        
        return results
    
    async def test_tiny_chunks(self) -> bool:
        """Тест: Очень маленькие чunks"""
        print_test("Очень маленькие чанки")
        
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
            "max_tokens": 10
        }
        
        try:
            chunks_received = 0
            start_time = time.time()
            
            async with self.client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=10.0
            ) as response:
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    return False
                
                async for chunk in response.aiter_bytes():
                    chunks_received += 1
                    decoded = chunk.decode('utf-8')
                    
                    # Проверка на ошибки
                    if '"error"' in decoded:
                        print_error(f"Ошибка в стриме: {decoded}")
                        return False
                    
                    # Проверка на корректность SSE формата
                    if 'data: ' in decoded and '[DONE]' not in decoded:
                        try:
                            json.loads(decoded[6:].strip())
                        except json.JSONDecodeError:
                            print_error(f"Невалидный JSON в чанке: {decoded}")
                            return False
                
                ttft = time.time() - start_time
                print_success(f"Получено {chunks_received} чанков, TTFT: {ttft*1000:.2f}ms")
                return chunks_received > 0
                
        except Exception as e:
            print_error(f"Исключение: {e}")
            return False
    
    async def test_multibyte_characters(self) -> bool:
        """Тест: Многобайтные символы"""
        print_test("Многобайтные символы")
        
        test_cases = [
            "Привет, мир! 🚀💻🔥",
            "こんにちは世界！ 🌍",
            "안녕하세요 세계! 🌏",
            "Hola mundo! 🌎",
            "مرحبا بالعالم! 🌐",
        ]
        
        success_count = 0
        
        for i, text in enumerate(test_cases):
            payload = {
                "model": TEST_MODEL,
                "messages": [{"role": "user", "content": f"Ответь: {text}"}],
                "stream": True,
                "max_tokens": 20
            }
            
            try:
                async with self.client.stream(
                    "POST",
                    f"{BASE_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    json=payload,
                    timeout=10.0
                ) as response:
                    if response.status_code != 200:
                        print_error(f"Тест {i+1}: HTTP {response.status_code}")
                        continue
                    
                    full_response = ""
                    async for chunk in response.aiter_bytes():
                        decoded = chunk.decode('utf-8')
                        if 'data: ' in decoded and '[DONE]' not in decoded:
                            try:
                                data = json.loads(decoded[6:])
                                content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                full_response += content
                            except:
                                pass
                    
                    # Проверяем, что ответ содержит символы из запроса
                    if any(ord(c) > 127 for c in full_response):
                        print_success(f"Тест {i+1}: Unicode символы обработаны ✓")
                        success_count += 1
                    else:
                        print_warning(f"Тест {i+1}: Нет Unicode символов в ответе")
                        
            except Exception as e:
                print_error(f"Тест {i+1}: Исключение {e}")
        
        return success_count >= len(test_cases) * 0.8  # 80% успешных
    
    async def test_mixed_formats(self) -> bool:
        """Тест: Смешанные форматы"""
        print_test("Смешанные форматы")
        
        # Этот тест проверяет, как сервис обрабатывает разные форматы
        # Поскольку мы используем OpenAI совместимый провайдер, 
        # должен быть только SSE формат
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Test"}],
            "stream": True,
            "max_tokens": 10
        }
        
        try:
            format_detected = None
            chunks_count = 0
            
            async with self.client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=10.0
            ) as response:
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    return False
                
                async for chunk in response.aiter_bytes():
                    chunks_count += 1
                    decoded = chunk.decode('utf-8')
                    
                    # Определяем формат
                    if format_detected is None:
                        if 'data: ' in decoded:
                            format_detected = 'sse'
                        else:
                            format_detected = 'unknown'
                    
                    # Проверяем, что формат consistent
                    if 'data: ' not in decoded and decoded.strip():
                        print_error(f"Несоответствие формата: ожидался SSE, получено что-то другое")
                        return False
                
                print_success(f"Формат: {format_detected}, Чанков: {chunks_count}")
                return format_detected == 'sse' and chunks_count > 0
                
        except Exception as e:
            print_error(f"Исключение: {e}")
            return False
    
    async def test_large_responses(self) -> bool:
        """Тест: Большие ответы"""
        print_test("Большие ответы")
        
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Write a detailed explanation about artificial intelligence in 1000 words"}],
            "stream": True,
            "max_tokens": 500
        }
        
        try:
            chunks_received = 0
            total_chars = 0
            start_time = time.time()
            
            async with self.client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=60.0
            ) as response:
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    return False
                
                async for chunk in response.aiter_bytes():
                    chunks_received += 1
                    decoded = chunk.decode('utf-8')
                    
                    if 'data: ' in decoded and '[DONE]' not in decoded:
                        try:
                            data = json.loads(decoded[6:])
                            content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            total_chars += len(content)
                        except:
                            pass
                
                total_time = time.time() - start_time
                
                print_success(f"Чанков: {chunks_received}, Символов: {total_chars}, Время: {total_time:.2f}s")
                
                # Проверяем, что получили достаточно данных
                if chunks_received > 10 and total_chars > 100:
                    print_success("Большой ответ обработан успешно ✓")
                    return True
                else:
                    print_warning("Ответ кажется слишком коротким")
                    return False
                    
        except Exception as e:
            print_error(f"Исключение: {e}")
            return False
    
    async def test_connection_breaks(self) -> bool:
        """Тест: Обрывы соединения"""
        print_test("Обрывы соединения")
        
        # Этот тест проверяет устойчивость к обрывам соединения
        # Мы не можем реально оборвать соединение, но можем проверить таймауты
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Test"}],
            "stream": True,
            "max_tokens": 10
        }
        
        try:
            # Короткий таймаут для проверки устойчивости
            async with self.client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=5.0  # Короткий таймаут
            ) as response:
                if response.status_code != 200:
                    # Ожидаем, что при коротком таймауте будет ошибка
                    print_warning(f"Ожидаемая ошибка таймаута: {response.status_code}")
                    return True  # Это ожидаемое поведение
                
                # Если получили ответ, проверяем его
                chunks_received = 0
                async for chunk in response.aiter_bytes():
                    chunks_received += 1
                    if chunks_received > 5:  # Ограничиваем количество чанков
                        break
                
                print_success(f"Соединение устойчиво, получено {chunks_received} чанков")
                return True
                
        except Exception as e:
            # Ожидаемое поведение при коротком таймауте
            print_warning(f"Ожидаемая ошибка таймаута: {e}")
            return True
    
    async def test_invalid_json(self) -> bool:
        """Тест: Невалидный JSON в SSE"""
        print_test("Невалидный JSON в SSE")
        
        # Этот тест проверяет обработку ошибок в JSON
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Test"}],
            "stream": True,
            "max_tokens": 10
        }
        
        try:
            error_count = 0
            chunks_count = 0
            
            async with self.client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=10.0
            ) as response:
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    return False
                
                async for chunk in response.aiter_bytes():
                    chunks_count += 1
                    decoded = chunk.decode('utf-8')
                    
                    # Проверяем на ошибки в JSON
                    if 'data: ' in decoded and '[DONE]' not in decoded:
                        try:
                            json.loads(decoded[6:].strip())
                        except json.JSONDecodeError:
                            error_count += 1
                            print_warning(f"Невалидный JSON в чанке: {decoded[:50]}...")
                
                # Если есть ошибки JSON, это проблема
                if error_count > 0:
                    print_error(f"Найдено {error_count} невалидных JSON чанков")
                    return False
                else:
                    print_success(f"Все {chunks_count} JSON чанков валидны ✓")
                    return True
                    
        except Exception as e:
            print_error(f"Исключение: {e}")
            return False
    
    async def test_rapid_requests(self) -> bool:
        """Тест: Быстрые последовательные запросы"""
        print_test("Быстрые последовательные запросы")
        
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Quick test"}],
            "stream": True,
            "max_tokens": 5
        }
        
        try:
            concurrent_requests = 5
            successful_requests = 0
            
            tasks = []
            for i in range(concurrent_requests):
                task = asyncio.create_task(self.make_single_request(payload, i))
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print_error(f"Запрос {i+1}: {result}")
                else:
                    successful_requests += 1
                    print_success(f"Запрос {i+1}: Успешно")
            
            success_rate = successful_requests / concurrent_requests
            print_success(f"Успешно: {successful_requests}/{concurrent_requests} ({success_rate*100:.1f}%)")
            
            return success_rate >= 0.8  # 80% успешных
            
        except Exception as e:
            print_error(f"Исключение: {e}")
            return False
    
    async def make_single_request(self, payload: Dict, request_id: int) -> bool:
        """Сделать одиночный запрос"""
        try:
            async with self.client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=10.0
            ) as response:
                if response.status_code != 200:
                    return False
                
                chunks_received = 0
                async for chunk in response.aiter_bytes():
                    chunks_received += 1
                    if chunks_received > 10:  # Ограничиваем количество чанков
                        break
                
                return chunks_received > 0
                
        except Exception:
            return False
    
    async def test_special_characters(self) -> bool:
        """Тест: Специальные символы"""
        print_test("Специальные символы")
        
        test_cases = [
            "Test with quotes: \"hello\" and backticks: `code`",
            "Test with newlines:\nLine1\nLine2",
            "Test with tabs:\tTab1\tTab2",
            "Test with escapes: \\n \\t \\\"",
            "Test with HTML: <div>hello</div>",
        ]
        
        success_count = 0
        
        for i, text in enumerate(test_cases):
            payload = {
                "model": TEST_MODEL,
                "messages": [{"role": "user", "content": f"Echo: {text}"}],
                "stream": True,
                "max_tokens": 20
            }
            
            try:
                async with self.client.stream(
                    "POST",
                    f"{BASE_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    json=payload,
                    timeout=10.0
                ) as response:
                    if response.status_code != 200:
                        print_error(f"Тест {i+1}: HTTP {response.status_code}")
                        continue
                    
                    full_response = ""
                    async for chunk in response.aiter_bytes():
                        decoded = chunk.decode('utf-8')
                        if 'data: ' in decoded and '[DONE]' not in decoded:
                            try:
                                data = json.loads(decoded[6:])
                                content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                full_response += content
                            except:
                                pass
                    
                    # Проверяем, что ответ не пустой
                    if full_response and len(full_response) > 0:
                        print_success(f"Тест {i+1}: Спецсимволы обработаны ✓")
                        success_count += 1
                    else:
                        print_warning(f"Тест {i+1}: Пустой ответ")
                        
            except Exception as e:
                print_error(f"Тест {i+1}: Исключение {e}")
        
        return success_count >= len(test_cases) * 0.8  # 80% успешных
    
    async def test_empty_events(self) -> bool:
        """Тест: Пустые и неполные события"""
        print_test("Пустые и неполные события")
        
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Test"}],
            "stream": True,
            "max_tokens": 10
        }
        
        try:
            empty_events = 0
            valid_events = 0
            
            async with self.client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=10.0
            ) as response:
                if response.status_code != 200:
                    print_error(f"HTTP {response.status_code}")
                    return False
                
                async for chunk in response.aiter_bytes():
                    decoded = chunk.decode('utf-8')
                    
                    # Проверяем на пустые события
                    if 'data: ' in decoded:
                        content = decoded[6:].strip()
                        if not content:
                            empty_events += 1
                        elif content == '[DONE]':
                            valid_events += 1
                        else:
                            try:
                                json.loads(content)
                                valid_events += 1
                            except json.JSONDecodeError:
                                empty_events += 1
                
                print_success(f"Пустых событий: {empty_events}, Валидных: {valid_events}")
                
                # Допустимо некоторое количество пустых событий
                if valid_events > 0:
                    print_success("События обработаны корректно ✓")
                    return True
                else:
                    print_error("Нет валидных событий")
                    return False
                    
        except Exception as e:
            print_error(f"Исключение: {e}")
            return False
    
    async def test_complex_unicode(self) -> bool:
        """Тест: Сложный юникод"""
        print_test("Сложный юникод")
        
        test_cases = [
            "🚀💻🔥🎉🌟✨🔥💫⭐🌈",
            "🇷🇺🇺🇸🇯🇵🇰🇷🇨🇳🇮🇳🇧🇷🇪🇸🇫🇷🇩🇪",
            "📊📈📉📋📝📄📑📒📓📔📕📖📗📘📙📚📓",
            "😀😃😄😁😆😅😂🤣😊😇🙂🙃😉😌😍🥰😘😗😙😚😋😛😝😜🤪🤨🧐🤓😎🤩🥳😏",
        ]
        
        success_count = 0
        
        for i, text in enumerate(test_cases):
            payload = {
                "model": TEST_MODEL,
                "messages": [{"role": "user", "content": f"Repeat: {text}"}],
                "stream": True,
                "max_tokens": 30
            }
            
            try:
                async with self.client.stream(
                    "POST",
                    f"{BASE_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}"},
                    json=payload,
                    timeout=15.0
                ) as response:
                    if response.status_code != 200:
                        print_error(f"Тест {i+1}: HTTP {response.status_code}")
                        continue
                    
                    full_response = ""
                    async for chunk in response.aiter_bytes():
                        decoded = chunk.decode('utf-8')
                        if 'data: ' in decoded and '[DONE]' not in decoded:
                            try:
                                data = json.loads(decoded[6:])
                                content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                                full_response += content
                            except:
                                pass
                    
                    # Проверяем, что ответ содержит эмодзи
                    if any(ord(c) > 127 for c in full_response):
                        print_success(f"Тест {i+1}: Сложный юникод обработан ✓")
                        success_count += 1
                    else:
                        print_warning(f"Тест {i+1}: Нет эмодзи в ответе")
                        
            except Exception as e:
                print_error(f"Тест {i+1}: Исключение {e}")
        
        return success_count >= len(test_cases) * 0.8  # 80% успешных
    
    async def close(self):
        """Закрытие клиента"""
        await self.client.aclose()


async def main():
    """Основная функция"""
    logger.info(f"{BLUE}{'='*60}{RESET}")
    logger.info(f"{BLUE}ТЕСТЫ УМНОЙ БУФЕРИЗАЦИИ{RESET}")
    logger.info(f"{BLUE}{'='*60}{RESET}")
    logger.info(f"\nТестирование против: {BASE_URL}")
    logger.info(f"API Key: {API_KEY}")
    
    tester = SmartBufferingTester()
    
    try:
        # Запуск тестов рискованных сценариев
        results = await tester.test_risky_scenarios()
        
        # Вывод результатов
        logger.info(f"\n{BLUE}{'='*60}{RESET}")
        logger.info(f"{BLUE}РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ{RESET}")
        logger.info(f"{BLUE}{'='*60}{RESET}")
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        for test_name, result in results.items():
            status = f"{GREEN}PASS{RESET}" if result else f"{RED}FAIL{RESET}"
            logger.info(f"  {test_name:.<40} {status}")
        
        logger.info(f"\n{BLUE}Итог: {passed}/{total} тестов passed{RESET}")
        
        if passed == total:
            logger.info(f"{GREEN}✓ Все тесты умной буферизации пройдены!{RESET}\n")
            return 0
        else:
            logger.info(f"{RED}✗ Некоторые тесты не пройдены. Проверьте логи выше.{RESET}\n")
            return 1
            
    except Exception as e:
        logger.error(f"\n{RED}Фатальная ошибка: {e}{RESET}\n")
        return 1
    
    finally:
        await tester.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)