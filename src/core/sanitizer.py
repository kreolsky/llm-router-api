"""Message sanitization to strip non-standard fields that break strict providers."""
# SYSTEM: sanitizer — strips non-standard message/chunk fields

from typing import Any

from .logging import logger


class MessageSanitizer:
    """Strips non-standard service fields from messages and stream chunks."""

    SERVICE_FIELDS = ['done', '__stream_end__', '__internal__', 'stream_end']
    
    @classmethod
    def sanitize_messages(cls, messages: list[dict[str, Any]], enabled: bool = True) -> list[dict[str, Any]]:
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
    def sanitize_stream_chunk(cls, chunk: dict[str, Any], enabled: bool = True) -> dict[str, Any]:
        """Remove SERVICE_FIELDS from a streaming chunk when enabled.

        _sanitize_dict already rebuilds every nested dict and list it walks, so
        the result shares no mutable structure with the caller's chunk — the
        deep copy this used to make on top of that was pure duplication.
        """
        if not enabled:
            logger.debug("Stream chunk sanitization is disabled")
            return chunk

        clean_chunk, removed_fields = cls._sanitize_dict(chunk)

        if removed_fields:
            logger.info("Stream chunk sanitization completed", extra={
                "sanitization": {
                    "total_removed_fields": len(removed_fields),
                    "removed_fields": removed_fields,
                    "choices_count": len(clean_chunk.get("choices", [])),
                }
            })

        return clean_chunk

    @classmethod
    def _sanitize_dict(cls, data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
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
