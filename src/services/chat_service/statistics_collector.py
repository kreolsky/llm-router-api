"""
Statistics Collector Module

This module provides the StatisticsCollector class for collecting and calculating
performance metrics during chat completion requests.

The StatisticsCollector tracks various timing and token metrics including:
- Prompt processing time and tokens
- Completion generation time and tokens  
- Total processing time and tokens
- Tokens per second calculations for both prompt and completion

This class is designed to be used by both the ChatService and StreamProcessor
to provide comprehensive performance insights for chat completion operations.
"""

import time
from typing import Dict, Any

from ...core.logging import logger, PerformanceLogger


class StatisticsCollector:
    """
    Collector for timing and token statistics during chat completion processing.
    
    This class tracks various performance metrics including:
    - Prompt processing time
    - Completion generation time  
    - Token counts for prompt and completion
    - Tokens per second calculations
    
    The collector provides a unified interface for timing different phases of
    chat completion processing and calculating derived performance metrics.
    
    Attributes:
        start_time (float): Timestamp when processing started (seconds since epoch)
        prompt_end_time (float): Timestamp when prompt processing completed
        completion_end_time (float): Timestamp when completion generation completed
        prompt_tokens (int): Number of tokens in the prompt
        completion_tokens (int): Number of tokens in the completion
        total_tokens (int): Total tokens processed (prompt + completion)
    """
    
    def __init__(self):
        """
        Initialize a new StatisticsCollector instance.
        
        All timing and token counters are initialized to zero or None.
        The collector starts in an uninitialized state until start_timing() is called.
        """
        self.start_time = None
        self.prompt_end_time = None
        self.completion_end_time = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
    
    def start_timing(self):
        """
        Start the timing measurement.
        
        This method should be called at the beginning of the request processing
        to initialize the timing measurements. It sets the start_time to the
        current time and prepares the collector for subsequent timing marks.
        
        Note:
            This method must be called before any other timing methods.
        """
        self.start_time = time.time()
    
    def mark_prompt_complete(self, prompt_tokens: int = 0):
        """
        Mark the completion of prompt processing.
        
        This method should be called when the prompt has been fully processed
        and the model is about to start generating the completion. It records
        the time and token count for the prompt processing phase.
        
        Args:
            prompt_tokens (int): Number of tokens in the processed prompt.
                Defaults to 0 if not provided.
        """
        self.prompt_end_time = time.time()
        self.prompt_tokens = prompt_tokens
    
    def mark_completion_complete(self, completion_tokens: int = 0):
        """
        Mark the completion of response generation.
        
        This method should be called when the model has finished generating
        the completion. It records the time and token count for the completion
        generation phase and calculates the total tokens.
        
        Args:
            completion_tokens (int): Number of tokens in the generated completion.
                Defaults to 0 if not provided.
        """
        self.completion_end_time = time.time()
        self.completion_tokens = completion_tokens
        self.total_tokens = self.prompt_tokens + self.completion_tokens
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Calculate and return comprehensive statistics.
        
        This method computes all derived metrics based on the collected timing
        and token data. It returns a dictionary with both raw measurements and
        calculated performance metrics.
        
        Returns:
            Dict[str, Any]: Dictionary containing comprehensive statistics:
                - prompt_tokens (int): Number of prompt tokens
                - prompt_time (float): Time spent processing prompt (seconds, rounded to 2 decimals)
                - prompt_tokens_per_sec (float): Prompt tokens per second (rounded to 2 decimals)
                - completion_tokens (int): Number of completion tokens  
                - completion_time (float): Time spent generating completion (seconds, rounded to 2 decimals)
                - completion_tokens_per_sec (float): Completion tokens per second (rounded to 2 decimals)
                - total_tokens (int): Total tokens processed
                - total_time (float): Total processing time (seconds, rounded to 2 decimals)
                
            Returns empty dict if timing hasn't been started (start_timing() not called).
        """
        if not self.start_time:
            return {}
        
        total_time = time.time() - self.start_time
        
        # Calculate prompt processing time
        prompt_time = self.prompt_end_time - self.start_time if self.prompt_end_time else 0
        
        # Calculate completion generation time
        completion_time = self.completion_end_time - self.prompt_end_time if self.completion_end_time and self.prompt_end_time else 0
        
        # Calculate tokens per second
        prompt_tokens_per_sec = self.prompt_tokens / prompt_time if prompt_time > 0 else 0
        completion_tokens_per_sec = self.completion_tokens / completion_time if completion_time > 0 else 0
        
        return {
            "prompt_tokens": self.prompt_tokens,
            "prompt_time": round(prompt_time, 2),
            "prompt_tokens_per_sec": round(prompt_tokens_per_sec, 2),
            "completion_tokens": self.completion_tokens,
            "completion_time": round(completion_time, 2),
            "completion_tokens_per_sec": round(completion_tokens_per_sec, 2),
            "total_tokens": self.total_tokens,
            "total_time": round(total_time, 2)
        }