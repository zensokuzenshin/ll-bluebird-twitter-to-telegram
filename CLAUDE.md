# Project Requirements

## Twitter Forward to Telegram

1. The webhook handler should accept any JSON payload format and log it for debugging
2. Classes for Tweet and Author should have optional fields with `extra = "allow"` to accept additional fields not explicitly modeled
3. When implementing direct search functionality:
   - Bypass FastAPI and use direct CLI approach
   - Allow command-line parameters for query, limit, type, and pagination
4. All tweets must be automatically translated from Japanese to Korean
5. Tweet formatting should:
   - Omit author name and username (since they'll be sent as the mapped bot account)
   - Include tweet text 
   - Show tweet posted date and time in KST (UTC+9) in format "MM.DD. HH:MM"
   - Include original link as "원본 링크"
   - Use italics for date and link to give a muted appearance
   - Disable link previews in Telegram

## Development Context and Preferences

1. Debugging first, then functionality:
   - Implement logging for payloads to understand their structure
   - Make data models flexible to handle variations in payload format
   - Only forward to Telegram after payload structure is verified

2. Command line functionality:
   - Implement direct Twitter API access without going through FastAPI
   - Support pagination via cursor parameter
   - Allow toggling of Telegram forwarding for testing
   - Properly parse Twitter date format at the model level

3. Code style preferences:
   - Keep models simple with optional fields rather than duplicate field names
   - Use proper error handling and logging
   - Maintain clear distinction between webhook handler and CLI functionality
   - Use modular architecture with separate modules for tweet, translate, and telegram functionality 

4. Translation requirements:
   - Always translate tweets to Korean before forwarding
   - Fall back to original text only if translation fails
   - Log translation status for debugging purposes
   - Use the Anthropic Claude API for high-quality natural translation