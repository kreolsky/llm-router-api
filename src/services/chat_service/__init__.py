"""
Chat Service Package

This package provides modular components for handling chat completion requests
in the NNP LLM Router system.

The package is organized into three main modules, each with a specific responsibility:

Modules:
- statistics_collector: Performance metrics collection and timing calculations
- stream_processor: Streaming response processing and format standardization  
- chat_service: Main chat completion coordination and request handling

This decomposition replaces the monolithic chat_service.py file with a modular
structure that follows single responsibility principles and improves maintainability.

Usage:
    from src.services.chat_service import ChatService, StreamProcessor, StatisticsCollector
    
    # Initialize the main service
    chat_service = ChatService(config_manager, httpx_client, model_service)
    
    # Use individual components as needed
    statistics = StatisticsCollector()
    stream_processor = StreamProcessor()
"""

from .statistics_collector import StatisticsCollector
from .stream_processor import StreamProcessor
from .chat_service import ChatService

__all__ = [
    "StatisticsCollector",
    "StreamProcessor", 
    "ChatService"
]