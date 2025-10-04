#!/usr/bin/env python3
"""
Внешний тест для измерения TTFT (Time To First Token)
Тестирование через HTTP запросы к работающему сервису
"""

import asyncio
import sys
import httpx
import time
import statistics
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


def print_test(name: str):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}ТЕСТ: {name}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")


def print_success(msg: str):
    print(f"{GREEN}✓ {msg}{RESET}")


def print_error(msg: str):
    print(f"{RED}✗ {msg}{RESET}")


def print_warning(msg: str):
    print(f"{YELLOW}⚠ {msg}{RESET}")


class TTFTTester:
    """Тестер TTFT через внешние HTTP запросы"""
    
    def __init__(self):
        self.client = httpx.AsyncClient()
    
    async def measure_single_ttft(self, payload: Dict[str, Any], test_name: str = "") -> Dict[str, float]:
        """Измерение TTFT для одного запроса"""
        start_time = time.time()
        first_token_time = None
        token_count = 0
        
        try:
            async with self.client.stream(
                "POST",
                f"{BASE_URL}/v1/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json=payload,
                timeout=30.0
            ) as response:
                if response.status_code != 200:
                    return {"error": f"HTTP {response.status_code}"}
                
                async for chunk in response.aiter_bytes():
                    if first_token_time is None:
                        first_token_time = time.time()
                        ttft = first_token_time - start_time
                        break
                    
                    # Извлекаем токен из SSE
                    decoded = chunk.decode('utf-8')
                    if 'data: ' in decoded and '[DONE]' not in decoded:
                        try:
                            data = json.loads(decoded[6:])
                            content = data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if content:
                                token_count += 1
                        except:
                            pass
                
                return {
                    "ttft_ms": ttft * 1000,
                    "first_token_time": first_token_time,
                    "start_time": start_time,
                    "token_count": token_count,
                    "test_name": test_name
                }
                
        except Exception as e:
            return {"error": str(e)}
    
    async def test_basic_ttft(self) -> Dict[str, Any]:
        """Базовый тест TTFT"""
        print_test("Базовый тест TTFT")
        
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Hello! Tell me about AI."}],
            "stream": True,
            "max_tokens": 50
        }
        
        result = await self.measure_single_ttft(payload, "Базовый запрос")
        
        if "error" in result:
            print_error(f"Ошибка: {result['error']}")
            return {"success": False, "result": result}
        
        print_success(f"TTFT: {result['ttft_ms']:.2f}ms")
        print_success(f"Токенов: {result['token_count']}")
        
        return {"success": True, "result": result}
    
    async def test_ttft_comparison(self) -> Dict[str, Any]:
        """Сравнение TTFT для разных типов запросов"""
        print_test("Сравнение TTFT для разных типов запросов")
        
        test_cases = [
            {
                "name": "Простой запрос",
                "payload": {
                    "model": TEST_MODEL,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "stream": True,
                    "max_tokens": 10
                }
            },
            {
                "name": "Запрос с эмодзи",
                "payload": {
                    "model": TEST_MODEL,
                    "messages": [{"role": "user", "content": "Привет! 🚀"}],
                    "stream": True,
                    "max_tokens": 20
                }
            },
            {
                "name": "Сложный запрос",
                "payload": {
                    "model": TEST_MODEL,
                    "messages": [{"role": "user", "content": "Explain quantum computing in simple terms"}],
                    "stream": True,
                    "max_tokens": 100
                }
            },
            {
                "name": "Контекстный запрос",
                "payload": {
                    "model": TEST_MODEL,
                    "messages": [
                        {"role": "user", "content": "I'm learning about machine learning"},
                        {"role": "assistant", "content": "That's great! Machine learning is a fascinating field."},
                        {"role": "user", "content": "Can you tell me more about neural networks?"}
                    ],
                    "stream": True,
                    "max_tokens": 50
                }
            }
        ]
        
        results = []
        
        for test_case in test_cases:
            print(f"\n📊 Тест: {test_case['name']}")
            result = await self.measure_single_ttft(test_case['payload'], test_case['name'])
            
            if "error" in result:
                print_error(f"Ошибка: {result['error']}")
                results.append({"name": test_case['name'], "error": result['error']})
            else:
                print_success(f"TTFT: {result['ttft_ms']:.2f}ms")
                print_success(f"Токенов: {result['token_count']}")
                results.append(result)
        
        # Анализ результатов
        valid_results = [r for r in results if "error" not in r]
        
        if valid_results:
            ttft_values = [r['ttft_ms'] for r in valid_results]
            avg_ttft = statistics.mean(ttft_values)
            min_ttft = min(ttft_values)
            max_ttft = max(ttft_values)
            
            print(f"\n📈 Статистика TTFT:")
            print(f"   Среднее: {avg_ttft:.2f}ms")
            print(f"   Минимум: {min_ttft:.2f}ms")
            print(f"   Максимум: {max_ttft:.2f}ms")
            
            return {
                "success": True,
                "results": results,
                "statistics": {
                    "avg_ttft": avg_ttft,
                    "min_ttft": min_ttft,
                    "max_ttft": max_ttft,
                    "count": len(valid_results)
                }
            }
        else:
            return {"success": False, "results": results}
    
    async def test_concurrent_ttft(self) -> Dict[str, Any]:
        """Тест TTFT при конкурентных запросах"""
        print_test("TTFT при конкурентных запросах")
        
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Quick test"}],
            "stream": True,
            "max_tokens": 10
        }
        
        concurrent_requests = 5
        tasks = []
        
        for i in range(concurrent_requests):
            task = asyncio.create_task(
                self.measure_single_ttft(payload, f"Конкурентный запрос {i+1}")
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print_error(f"Запрос {i+1}: {result}")
            elif "error" in result:
                print_error(f"Запрос {i+1}: {result['error']}")
            else:
                print_success(f"Запрос {i+1}: TTFT {result['ttft_ms']:.2f}ms")
                successful_results.append(result)
        
        if successful_results:
            ttft_values = [r['ttft_ms'] for r in successful_results]
            avg_ttft = statistics.mean(ttft_values)
            
            print(f"\n📊 Конкурентная статистика:")
            print(f"   Успешных запросов: {len(successful_results)}/{concurrent_requests}")
            print(f"   Среднее TTFT: {avg_ttft:.2f}ms")
            
            return {
                "success": True,
                "results": successful_results,
                "concurrent_stats": {
                    "avg_ttft": avg_ttft,
                    "success_rate": len(successful_results) / concurrent_requests
                }
            }
        else:
            return {"success": False, "results": results}
    
    async def test_ttft_stability(self) -> Dict[str, Any]:
        """Тест стабильности TTFT"""
        print_test("Стабильность TTFT")
        
        payload = {
            "model": TEST_MODEL,
            "messages": [{"role": "user", "content": "Test stability"}],
            "stream": True,
            "max_tokens": 10
        }
        
        iterations = 10
        results = []
        
        for i in range(iterations):
            print(f"  Итерация {i+1}/{iterations}...")
            result = await self.measure_single_ttft(payload, f"Стабильность {i+1}")
            
            if "error" in result:
                print_error(f"Ошибка в итерации {i+1}: {result['error']}")
            else:
                results.append(result['ttft_ms'])
                print(f"    TTFT: {result['ttft_ms']:.2f}ms")
        
        if results:
            avg_ttft = statistics.mean(results)
            stdev_ttft = statistics.stdev(results) if len(results) > 1 else 0
            min_ttft = min(results)
            max_ttft = max(results)
            
            print(f"\n📈 Статистика стабильности:")
            print(f"   Среднее: {avg_ttft:.2f}ms")
            print(f"   Стандартное отклонение: {stdev_ttft:.2f}ms")
            print(f"   Минимум: {min_ttft:.2f}ms")
            print(f"   Максимум: {max_ttft:.2f}ms")
            print(f"   Коэффициент вариации: {(stdev_ttft/avg_ttft)*100:.1f}%")
            
            return {
                "success": True,
                "results": results,
                "stability_stats": {
                    "avg_ttft": avg_ttft,
                    "stdev_ttft": stdev_ttft,
                    "min_ttft": min_ttft,
                    "max_ttft": max_ttft,
                    "coefficient_of_variation": (stdev_ttft/avg_ttft)*100
                }
            }
        else:
            return {"success": False, "results": []}
    
    async def run_comprehensive_ttft_test(self) -> Dict[str, Any]:
        """Комплексное тестирование TTFT"""
        print_test("Комплексное тестирование TTFT")
        
        all_results = {}
        
        # Базовый тест
        basic_result = await self.test_basic_ttft()
        all_results["basic"] = basic_result
        
        # Сравнение разных типов запросов
        comparison_result = await self.test_ttft_comparison()
        all_results["comparison"] = comparison_result
        
        # Конкурентные запросы
        concurrent_result = await self.test_concurrent_ttft()
        all_results["concurrent"] = concurrent_result
        
        # Стабильность
        stability_result = await self.test_ttft_stability()
        all_results["stability"] = stability_result
        
        return all_results
    
    async def close(self):
        """Закрытие клиента"""
        await self.client.aclose()


def analyze_ttft_results(results: Dict[str, Any]) -> None:
    """Анализ результатов TTFT"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}АНАЛИЗ РЕЗУЛЬТАТОВ TTFT{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    
    # Базовый тест
    if "basic" in results and results["basic"]["success"]:
        basic = results["basic"]["result"]
        print(f"🎯 Базовый TTFT: {basic['ttft_ms']:.2f}ms")
        
        # Оценка качества
        if basic['ttft_ms'] < 1000:
            print(f"{GREEN}✓ Отличный TTFT (< 1s){RESET}")
        elif basic['ttft_ms'] < 2000:
            print(f"{YELLOW}⚠️  Хороший TTFT (1-2s){RESET}")
        else:
            print(f"{RED}✗ Медленный TTFT (> 2s){RESET}")
    
    # Сравнение запросов
    if "comparison" in results and results["comparison"]["success"]:
        comparison = results["comparison"]
        stats = comparison["statistics"]
        
        print(f"\n📊 Сравнение типов запросов:")
        print(f"   Среднее TTFT: {stats['avg_ttft']:.2f}ms")
        print(f"   Лучший результат: {stats['min_ttft']:.2f}ms")
        print(f"   Худший результат: {stats['max_ttft']:.2f}ms")
        
        # Вывод результатов по каждому типу
        for result in comparison["results"]:
            if "error" not in result:
                print(f"   {result['test_name']}: {result['ttft_ms']:.2f}ms")
    
    # Конкурентные запросы
    if "concurrent" in results and results["concurrent"]["success"]:
        concurrent = results["concurrent"]
        stats = concurrent["concurrent_stats"]
        
        print(f"\n🔄 Конкурентные запросы:")
        print(f"   Успешность: {stats['success_rate']*100:.1f}%")
        print(f"   Среднее TTFT: {stats['avg_ttft']:.2f}ms")
    
    # Стабильность
    if "stability" in results and results["stability"]["success"]:
        stability = results["stability"]
        stats = stability["stability_stats"]
        
        print(f"\n📈 Стабильность:")
        print(f"   Среднее TTFT: {stats['avg_ttft']:.2f}ms")
        print(f"   Стандартное отклонение: {stats['stdev_ttft']:.2f}ms")
        print(f"   Коэффициент вариации: {stats['coefficient_of_variation']:.1f}%")
        
        # Оценка стабильности
        if stats['coefficient_of_variation'] < 20:
            print(f"{GREEN}✓ Высокая стабильность (< 20% вариации){RESET}")
        elif stats['coefficient_of_variation'] < 50:
            print(f"{YELLOW}⚠️  Удовлетворительная стабильность (20-50%){RESET}")
        else:
            print(f"{RED}✗ Низкая стабильность (> 50%){RESET}")
    
    # Общие рекомендации
    print(f"\n💡 Рекомендации:")
    
    # Проверяем, есть ли данные для анализа
    has_data = any(
        key in results and results[key]["success"] 
        for key in ["basic", "comparison", "concurrent", "stability"]
    )
    
    if has_data:
        # Проверяем базовый TTFT
        basic_ttft = None
        if "basic" in results and results["basic"]["success"]:
            basic_ttft = results["basic"]["result"]["ttft_ms"]
        
        if basic_ttft:
            if basic_ttft > 3000:
                print(f"   🔧 TTFT слишком высокий ({basic_ttft:.0f}ms). Рекомендуется:")
                print(f"      - Проверить сетевую задержку")
                print(f"      - Оптимизировать буферизацию")
                print(f"      - Рассмотреть использование CDN")
            elif basic_ttft > 1500:
                print(f"   ⚠️  TTFT в пределах нормы ({basic_ttft:.0f}ms), но может быть улучшен")
            else:
                print(f"   ✓ TTFT в хорошем диапазоне ({basic_ttft:.0f}ms)")
        
        # Проверяем стабильность
        if "stability" in results and results["stability"]["success"]:
            cv = results["stability"]["stability_stats"]["coefficient_of_variation"]
            if cv > 50:
                print(f"   🔧 Низкая стабильность TTFT. Рекомендуется:")
                print(f"      - Проверить нагрузку на сервер")
                print(f"      - Оптимизировать обработку запросов")
                print(f"      - Рассмотреть кеширование")
        
        print(f"   📊 Для мониторинга TTFT рекомендуется:")
        print(f"      - Внедрить логирование TTFT")
        print(f"      - Установить пороги оповещения")
        print(f"      - Регулярно анализировать тренды")
    else:
        print(f"   ❌ Недостаточно данных для анализа")


async def main():
    """Основная функция"""
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}ИЗМЕРЕНИЕ TTFT (TIME TO FIRST TOKEN){RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"\nТестирование против: {BASE_URL}")
    print(f"API Key: {API_KEY}")
    
    tester = TTFTTester()
    
    try:
        # Запуск комплексного тестирования
        results = await tester.run_comprehensive_ttft_test()
        
        # Анализ результатов
        analyze_ttft_results(results)
        
        # Итог
        successful_tests = sum(1 for v in results.values() if v.get("success", False))
        total_tests = len(results)
        
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}ИТОГОВЫЕ РЕЗУЛЬТАТЫ{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        print(f"Успешных тестов: {successful_tests}/{total_tests}")
        
        if successful_tests == total_tests:
            print(f"{GREEN}✓ Все тесты TTFT завершены успешно!{RESET}\n")
            return 0
        else:
            print(f"{YELLOW}⚠️  Некоторые тесты завершились с ошибками.{RESET}\n")
            return 1
            
    except Exception as e:
        print(f"\n{RED}Фатальная ошибка: {e}{RESET}\n")
        return 1
    
    finally:
        await tester.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)