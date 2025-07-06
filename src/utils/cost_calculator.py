from typing import Dict, Any

class CostCalculator:
    @staticmethod
    def calculate_total_cost(prompt_tokens: int, completion_tokens: int, pricing: Dict[str, float]) -> Dict[str, float]:
        prompt_cost = prompt_tokens * float(pricing.get("prompt", 0))
        completion_cost = completion_tokens * float(pricing.get("completion", 0))
        total_cost = prompt_cost + completion_cost
        return {
            "prompt_cost": prompt_cost,
            "completion_cost": completion_cost,
            "total_cost": total_cost
        }
