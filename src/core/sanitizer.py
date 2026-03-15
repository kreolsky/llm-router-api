"""Message sanitization to strip non-standard fields that break strict providers."""

from typing import Dict, Any, List, Tuple

from .logging import logger


class MessageSanitizer:
    """Strips non-standard service fields from messages and stream chunks."""

    SERVICE_FIELDS = ['done', '__stream_end__', '__internal__', 'stream_end']
    
    @classmethod
    def sanitize_messages(cls, messages: List[Dict[str, Any]], enabled: bool = True) -> List[Dict[str, Any]]:
        """Remove SERVICE_FIELDS from each message dict when sanitization is enabled."""
        if not enabled:
            logger.debug("Message sanitization is disabled")
            return messages
        
        logger.debug(f"Sanitizing {len(messages)} messages from client-side contamination")
        sanitized = []
        removed_fields_count = 0
        
        for i, message in enumerate(messages):
            clean_message = message.copy()
            removed_in_message = []
            
            for field in cls.SERVICE_FIELDS:
                if field in clean_message:
                    removed_in_message.append(field)
                    clean_message.pop(field, None)
                    removed_fields_count += 1
            
            if removed_in_message:
                logger.debug(f"Removed fields {removed_in_message} from message {i}")
            
            sanitized.append(clean_message)
        
        if removed_fields_count > 0:
            logger.info(f"Message sanitization removed {removed_fields_count} service fields from {len(messages)} messages")
        
        return sanitized
    
    @classmethod
    def sanitize_stream_chunk(cls, chunk: Dict[str, Any], enabled: bool = True) -> Dict[str, Any]:
        """Remove SERVICE_FIELDS from a streaming chunk's choices/delta when enabled."""
        if not enabled:
            logger.debug("Stream chunk sanitization is disabled")
            return chunk
        
        clean_chunk = chunk.copy()
        removed_fields = []
        
        if "choices" in clean_chunk and clean_chunk["choices"]:
            for i, choice in enumerate(clean_chunk["choices"]):
                choice_removed = []
                
                if "delta" in choice:
                    sanitized_delta, delta_removed = cls._sanitize_dict(choice["delta"])
                    choice["delta"] = sanitized_delta
                    choice_removed.extend(delta_removed)
                
                sanitized_choice, choice_removed_extra = cls._sanitize_dict(choice)
                choice.update(sanitized_choice)
                choice_removed.extend(choice_removed_extra)
                
                if choice_removed:
                    logger.debug(f"Sanitized choice {i}, removed fields: {choice_removed}", extra={
                        "sanitization": {
                            "choice_index": i,
                            "removed_fields": choice_removed,
                            "choice_content": choice.get("delta", {}).get("content", "")[:50] + "..." if choice.get("delta", {}).get("content") else None
                        }
                    })
                    removed_fields.extend(choice_removed)
        
        if removed_fields:
            logger.info(f"Stream chunk sanitization completed", extra={
                "sanitization": {
                    "total_removed_fields": len(removed_fields),
                    "removed_fields": removed_fields,
                    "chunk_summary": {
                        "has_choices": "choices" in clean_chunk and len(clean_chunk["choices"]) > 0,
                        "choices_count": len(clean_chunk.get("choices", [])),
                        "has_content": any(choice.get("delta", {}).get("content") for choice in clean_chunk.get("choices", []))
                    }
                }
            })
        
        return clean_chunk
    
    @classmethod
    def _sanitize_dict(cls, data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Recursively remove SERVICE_FIELDS from a dict, returning (cleaned, removed_list)."""
        if not isinstance(data, dict):
            return data, []
        
        clean_data = data.copy()
        removed_fields = []
        
        for field in cls.SERVICE_FIELDS:
            if field in clean_data:
                removed_fields.append(field)
                logger.debug(f"Removing service field: {field}", extra={
                    "sanitization": {
                        "removed_field": field,
                        "field_value": str(clean_data[field])[:100] if clean_data[field] else None
                    }
                })
                clean_data.pop(field, None)
        
        for key, value in clean_data.items():
            if isinstance(value, dict):
                cleaned_nested, nested_removed = cls._sanitize_dict(value)
                clean_data[key] = cleaned_nested
                removed_fields.extend(nested_removed)
            elif isinstance(value, list):
                cleaned_list = []
                for item in value:
                    if isinstance(item, dict):
                        cleaned_item, item_removed = cls._sanitize_dict(item)
                        cleaned_list.append(cleaned_item)
                        removed_fields.extend(item_removed)
                    else:
                        cleaned_list.append(item)
                clean_data[key] = cleaned_list
        
        return clean_data, removed_fields
