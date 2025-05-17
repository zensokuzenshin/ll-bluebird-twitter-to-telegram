# Project Requirements

## Twitter Forward to Telegram

1. The webhook handler should accept any JSON payload format and log it for debugging
2. Classes for Tweet and Author should have optional fields with `extra = "allow"` to accept additional fields not explicitly modeled
3. When implementing direct search functionality:
   - Bypass FastAPI and use direct CLI approach
   - Allow command-line parameters for query, limit, type, and pagination

## Development Context and Preferences

1. Debugging first, then functionality:
   - Implement logging for payloads to understand their structure
   - Make data models flexible to handle variations in payload format
   - Only forward to Telegram after payload structure is verified

2. Command line functionality:
   - Implement direct Twitter API access without going through FastAPI
   - Support pagination via cursor parameter
   - Allow toggling of Telegram forwarding for testing

3. Code style preferences:
   - Keep models simple with optional fields rather than duplicate field names
   - Use proper error handling and logging
   - Maintain clear distinction between webhook handler and CLI functionality