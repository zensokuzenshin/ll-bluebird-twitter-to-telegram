import asyncio
import sys
import datetime
import logging
import config
from common import logger, direct_search_and_forward


async def cmd_fetch_and_send(args):
    """
    Fetch tweets and optionally send them to Telegram.
    
    Args:
        args: Command-line arguments after the subcommand
    """
    # Check if help is requested
    if not args or args[0] in ['-h', '--help']:
        print("Usage: fetch-and-send [options]")
        print("\nOptions:")
        print("  --limit=N            Maximum number of tweets to process (default: 5, max per page: 20)")
        print("                       Use --limit=0 to fetch all available tweets")
        print("  --type=Latest|Top    Type of search (default: Latest)")
        print("  --cursor=XYZ         Starting pagination cursor (will auto-follow to meet limit)")
        print("  --character=NAME     Send tweets as a specific character")
        print("  --no-forward         Only search without forwarding to Telegram")
        print("\nExamples:")
        print("  fetch-and-send --limit=3 --type=Latest")
        print("  fetch-and-send --character=Polka --limit=50")
        print("  fetch-and-send --limit=0  # Fetch all available tweets")
        print("  fetch-and-send --no-forward")
        print("\nAvailable characters:")
        for name in sorted(config.characters._character_config.keys()):
            char = config.characters._character_config[name]
            print(f"  - {name.capitalize()} (@{char.twitter_handle})")
        return

    # By default, search for tweets from all configured characters
    query = " OR ".join(f"from:{char.twitter_handle}" for char in config.characters._character_config.values())
    
    # Parse optional arguments
    requested_limit = 5  # Default limit
    max_page_size = 20   # Max tweets per page from API
    query_type = "Latest"
    forward = True
    cursor = ""
    character = None
    fetch_all = False
    
    for arg in args:
        if arg.startswith("--limit="):
            try:
                requested_limit = int(arg.split("=")[1])
                if requested_limit < 0:
                    print("Limit must be 0 or greater")
                    return
                if requested_limit == 0:
                    fetch_all = True
                    # Set an extremely high limit, though we'll stop when we run out of tweets
                    requested_limit = 1000000000  # 1 billion, effectively unlimited
            except:
                print(f"Invalid limit value: {arg}")
                return
        elif arg.startswith("--type="):
            query_type = arg.split("=")[1]
            if query_type not in ["Latest", "Top"]:
                print(f"Invalid query type: {query_type}. Must be 'Latest' or 'Top'")
                return
        elif arg.startswith("--cursor="):
            cursor = arg.split("=")[1]
        elif arg.startswith("--character="):
            character = arg.split("=")[1]
            # Verify character exists
            try:
                char_obj = getattr(config.characters, character)
                print(f"Using character: {character} (@{char_obj.twitter_handle})")
            except (AttributeError, KeyError):
                print(f"Character '{character}' not found. Available characters:")
                for char_name in config.characters._character_config.keys():
                    print(f"  - {char_name}")
                return
        elif arg == "--no-forward":
            forward = False
    
    # Auto-pagination to meet requested limit
    total_processed = 0
    all_results = []
    remaining_limit = requested_limit
    current_cursor = cursor
    
    if fetch_all:
        print("Fetching all available tweets...")
    else:
        print(f"Fetching up to {requested_limit} tweets...")
    
    while remaining_limit > 0:
        # Determine limit for this request (max 20 per page)
        current_limit = min(remaining_limit, max_page_size)
        
        # Run the search function for this page
        results = await direct_search_and_forward(
            query=query,
            query_type=query_type,
            limit=current_limit,
            forward_to_telegram=forward,
            cursor=current_cursor,
            character_name=character
        )
        
        # Check for errors
        if results.get("status") != "success":
            print(f"Error: {results.get('message', 'Unknown error')}")
            return
        
        # Process results
        count = results.get("count", 0)
        if count == 0:
            # No more tweets available
            break
            
        # Track processed tweets
        all_results.extend(results.get("results", []))
        total_processed += count
        
        # Update remaining limit
        remaining_limit -= count
        
        # Check if there are more pages available and update cursor
        next_cursor = results.get("next_cursor", "")
        has_next_page = results.get("has_next_page", False)
        
        if not has_next_page or not next_cursor:
            logger.info("No more pages available.")
            break
            
        # Update cursor for next page
        logger.info(f"Next cursor: {next_cursor}")
        current_cursor = next_cursor
        print(f"Fetched {count} tweets, continuing to next page...")
    
    # Sort tweets by date before forwarding (if needed)
    if forward and all_results:
        print("Sorting tweets by date before sending to Telegram...")
        try:
            # Create a list of (result, date) tuples for sorting
            dated_results = []
            
            for result in all_results:
                # Skip results without tweet_id or not a dict
                if not isinstance(result, dict) or 'tweet_id' not in result:
                    dated_results.append((result, None))  # Will go to the end
                    continue
                
                # Extract the tweet ID and try to determine its date
                tweet_id = result.get('tweet_id')
                tweet_date = None
                
                # We don't have direct access to the tweet data from here
                # Use timestamp or other information if available in the result
                # For now, we'll rely on the order we received the tweets
                # Twitter API typically returns tweets in reverse chronological order
                # So we'll use the index as a proxy for time
                index_in_results = all_results.index(result)
                dated_results.append((result, index_in_results))
            
            # Sort by index (proxy for time), with None values at the end
            # Reverse the sort to get oldest first (smallest index = oldest)
            sorted_results = [r[0] for r in sorted(
                dated_results,
                key=lambda x: (x[1] is None, -x[1] if x[1] is not None else None)
            )]
            
            # Replace all_results with the sorted version
            all_results = sorted_results
            print(f"Sorted {len(sorted_results)} tweets for chronological sending")
        except Exception as e:
            print(f"Warning: Failed to sort tweets: {str(e)}")
            print("Will process tweets in their original order")
    
    # Print summary
    print(f"\nSearch for: {query}")
    print(f"Total tweets processed: {total_processed}")
    
    # Show additional info if fetching all available tweets
    if fetch_all:
        print(f"All available tweets have been processed.")
    
    # Count successful forwards
    if forward:
        successful = sum(1 for r in all_results if isinstance(r, dict) and r.get("forwarded") is True)
        print(f"Successfully forwarded {successful} tweets to Telegram")
    else:
        print("Tweets found but not forwarded (--no-forward specified)")


async def cmd_dump_tweets(args):
    """
    Fetch tweets and save them to a JSON file.
    
    Args:
        args: Command-line arguments after the subcommand
    """
    import json
    import os
    from datetime import datetime
    from tweet import search_tweets
    
    # Check if help is requested
    if not args or args[0] in ['-h', '--help']:
        print("Usage: dump-tweets [options]")
        print("\nOptions:")
        print("  --limit=N            Maximum number of tweets to fetch (default: 20, auto-paginates)")
        print("                       Use --limit=0 to fetch all available tweets")
        print("  --type=Latest|Top    Type of search (default: Latest)")
        print("  --cursor=XYZ         Starting pagination cursor")
        print("  --file=PATH          File path to save tweets (default: tweets_YYYYMMDD_HHMMSS.json)")
        print("  --append             Append to existing file instead of creating a new one")
        print("\nExamples:")
        print("  dump-tweets --limit=50 --type=Latest")
        print("  dump-tweets --file=my_tweets.json --append")
        print("  dump-tweets --limit=0 --file=all_tweets.json  # Fetch all available tweets")
        return

    # By default, search for tweets from all configured characters
    query = " OR ".join(f"from:{char.twitter_handle}" for char in config.characters._character_config.values())
    
    # Parse optional arguments
    requested_limit = 20  # Default limit
    max_page_size = 20    # Max tweets per page from API
    query_type = "Latest"
    starting_cursor = ""
    append_mode = False
    fetch_all = False
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = f"tweets_{timestamp}.json"
    
    for arg in args:
        if arg.startswith("--limit="):
            try:
                requested_limit = int(arg.split("=")[1])
                if requested_limit < 0:
                    print("Limit must be 0 or greater")
                    return
                if requested_limit == 0:
                    fetch_all = True
                    # Set an extremely high limit, though we'll stop when we run out of tweets
                    requested_limit = 1000000000  # 1 billion, effectively unlimited
            except:
                print(f"Invalid limit value: {arg}")
                return
        elif arg.startswith("--type="):
            query_type = arg.split("=")[1]
            if query_type not in ["Latest", "Top"]:
                print(f"Invalid query type: {query_type}. Must be 'Latest' or 'Top'")
                return
        elif arg.startswith("--cursor="):
            starting_cursor = arg.split("=")[1]
        elif arg.startswith("--file="):
            file_path = arg.split("=", 1)[1]
        elif arg == "--append":
            append_mode = True
    
    # Check if we should append to existing file
    existing_tweets = []
    if append_mode and os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_tweets = json.load(f)
            if not isinstance(existing_tweets, list):
                existing_tweets = []
                print(f"Warning: Existing file {file_path} does not contain a JSON list. Creating a new list.")
        except json.JSONDecodeError:
            print(f"Warning: Existing file {file_path} is not valid JSON. Creating a new list.")
    
    if fetch_all:
        print("Fetching all available tweets...")
    else:
        print(f"Fetching up to {requested_limit} tweets...")
    
    # Auto-pagination to meet requested limit
    all_tweets = []
    remaining_limit = requested_limit
    current_cursor = starting_cursor
    total_fetched = 0
    
    try:
        while remaining_limit > 0:
            # Determine limit for this request (max 20 per page)
            current_limit = min(remaining_limit, max_page_size)
            
            # Fetch tweets for this page
            logger.info(f"Searching Twitter with query: {query}, cursor: {current_cursor}")
            search_results = await search_tweets(query, query_type, current_cursor)
            tweets = search_results.get("tweets", [])
            
            if not tweets:
                logger.info("No more tweets found.")
                break
            
            # Limit the number of tweets for this page
            page_tweets = tweets[:current_limit]
            fetched_count = len(page_tweets)
            
            # Add to collection
            all_tweets.extend(page_tweets)
            total_fetched += fetched_count
            
            # Update remaining limit
            remaining_limit -= fetched_count
            
            print(f"Fetched {fetched_count} tweets...")
            
            # Check if there are more pages available and update cursor
            next_cursor = search_results.get("next_cursor", "")
            has_next_page = search_results.get("has_next_page", False)
            
            if not has_next_page or not next_cursor:
                logger.info("No more pages available.")
                break
                
            # Update cursor for next page
            logger.info(f"Next cursor: {next_cursor}")
            current_cursor = next_cursor
            
            # If we've reached the requested limit, stop
            if remaining_limit <= 0:
                break
        
        # Combine with existing tweets if in append mode
        final_tweets = existing_tweets + all_tweets
        
        # Save all tweets to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(final_tweets, f, indent=2, ensure_ascii=False)
        
        print(f"\nSuccessfully saved {total_fetched} new tweets to {file_path}")
        
        if len(existing_tweets) > 0:
            print(f"File now contains {len(final_tweets)} tweets total.")
        
        # Show message about fetching all tweets or limits
        if fetch_all:
            print("All available tweets have been fetched and saved.")
        elif total_fetched < requested_limit:
            print(f"Note: Only {total_fetched} tweets were available (requested {requested_limit}).")
    
    except Exception as e:
        logger.error(f"Error dumping tweets: {str(e)}")
        print(f"Error: {str(e)}")

async def cmd_send_admin_notification(args):
    """
    Send an admin notification to Telegram using Mai's token.
    
    Args:
        args: Command-line arguments after the subcommand
    """
    from telegram import send_telegram_message
    
    # Check if help is requested
    if not args or args[0] in ['-h', '--help']:
        print("Usage: send-admin-notification [message]")
        print("\nOptions:")
        print("  --no-header        Don't include the [관리자 공지] header")
        print("\nExamples:")
        print("  send-admin-notification 'Server maintenance scheduled for tomorrow'")
        print("  send-admin-notification --no-header 'Quick update about the timeline'")
        return
    
    # Parse options and extract message
    add_header = True
    message = None
    
    # Check for options first
    filtered_args = []
    for arg in args:
        if arg == "--no-header":
            add_header = False
        else:
            filtered_args.append(arg)
    
    # Get the message from remaining args
    if filtered_args:
        message = " ".join(filtered_args)
    
    if not message:
        print("Error: No message provided")
        return
    
    try:
        # Always use "Mai" character for admin notifications
        try:
            mai_character = config.characters.mai
        except (AttributeError, KeyError):
            print(f"Error: 'mai' character not found in configuration")
            return
        
        # Format the message with bold header if needed
        if add_header:
            formatted_message = f"<b>[관리자 공지]</b>\n\n{message}"
        else:
            formatted_message = message
        
        # Send the notification
        print(f"Sending admin notification as {mai_character.name}...")
        try:
            await send_telegram_message(mai_character, formatted_message)
            print("✓ Admin notification sent successfully")
        except Exception as e:
            # Error notification is already handled in send_telegram_message
            print(f"✗ Failed to send admin notification: {str(e)}")
        
    except Exception as e:
        print(f"Error sending admin notification: {str(e)}")


async def cmd_send_from_file(args):
    """
    Read tweets from a JSON file and send them to Telegram.
    
    Args:
        args: Command-line arguments after the subcommand
    """
    import json
    import os
    from tweet import Tweet, format_tweet_for_telegram
    from telegram import send_telegram_message
    
    # Import translation module - always needed now
    try:
        from translate import translate, TranslationError
    except ImportError:
        print("Error: Translation module not available. Make sure the translate.py file exists.")
        return
    
    # Check if help is requested
    if not args or args[0] in ['-h', '--help']:
        print("Usage: send-from-file [options]")
        print("\nOptions:")
        print("  --file=PATH          JSON file path containing tweets (required)")
        print("  --limit=N            Maximum number of tweets to send (default: all)")
        print("  --offset=N           Starting offset in the tweet list (default: 0)")
        print("  --character=NAME     Send all tweets as this character (optional)")
        print("  --dry-run            Don't actually send to Telegram, just simulate")
        print("\nExamples:")
        print("  send-from-file --file=tweets.json                     # Auto-match characters by username")
        print("  send-from-file --file=tweets.json --character=Polka   # Force all tweets as Polka")
        print("  send-from-file --file=tweets.json --limit=5 --dry-run # Test with 5 tweets")
        print("\nAvailable characters:")
        for name in sorted(config.characters._character_config.keys()):
            char = config.characters._character_config[name]
            print(f"  - {name.capitalize()} (@{char.twitter_handle})")
        return
    
    # Parse required arguments
    file_path = None
    character = None
    limit = None
    offset = 0
    dry_run = False
    
    for arg in args:
        if arg.startswith("--file="):
            file_path = arg.split("=", 1)[1]
        elif arg.startswith("--character="):
            character = arg.split("=")[1]
        elif arg.startswith("--translate="):
            # Keep for backward compatibility but display a notification
            print("Note: Translation is now automatic for all tweets. The --translate flag is no longer needed.")
        elif arg.startswith("--limit="):
            try:
                limit = int(arg.split("=")[1])
                if limit <= 0:
                    print("Limit must be greater than 0")
                    return
            except:
                print(f"Invalid limit value: {arg}")
                return
        elif arg.startswith("--offset="):
            try:
                offset = int(arg.split("=")[1])
                if offset < 0:
                    print("Offset must be 0 or greater")
                    return
            except:
                print(f"Invalid offset value: {arg}")
                return
        elif arg == "--dry-run":
            dry_run = True
    
    # Validate required parameters
    if not file_path:
        print("Error: --file parameter is required")
        return
    
    # Verify file exists
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found")
        return
    
    # Verify specified character exists if provided
    forced_character_obj = None
    if character:
        try:
            forced_character_obj = getattr(config.characters, character)
            print(f"Using character for all tweets: {character} (@{forced_character_obj.twitter_handle})")
        except (AttributeError, KeyError):
            print(f"Character '{character}' not found. Available characters:")
            for char_name in config.characters._character_config.keys():
                print(f"  - {char_name}")
            return
    else:
        print("No specific character selected. Will try to match characters by Twitter username.")
    
    try:
        # Read the JSON file
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                tweets_data = json.load(f)
            except json.JSONDecodeError:
                print(f"Error: '{file_path}' is not a valid JSON file")
                return
        
        # Verify tweets_data is a list
        if not isinstance(tweets_data, list):
            print(f"Error: File does not contain a JSON array of tweets")
            return
        
        # Get the total count and subset based on offset and limit
        total_tweets = len(tweets_data)
        start_idx = offset
        end_idx = total_tweets if limit is None else min(offset + limit, total_tweets)
        
        # Check if offset is valid
        if start_idx >= total_tweets:
            print(f"Error: Offset {offset} is beyond the end of the file (contains {total_tweets} tweets)")
            return
        
        # Get the subset of tweets to process
        tweets_to_process = tweets_data[start_idx:end_idx]
        count_to_process = len(tweets_to_process)
        
        print(f"File contains {total_tweets} tweets")
        print(f"Processing tweets {start_idx+1} to {end_idx} ({count_to_process} tweets)")
        
        # Sort tweets by date before processing
        print("Sorting tweets by date (oldest to newest)...")
        try:
            # Try to parse dates from tweets and sort
            dated_tweets = []
            for tweet_data in tweets_to_process:
                # First try to use parsed_date if it exists
                if 'parsed_date' in tweet_data:
                    dated_tweets.append((tweet_data, tweet_data['parsed_date']))
                    continue
                    
                # Otherwise, try to parse from createdAt
                if 'createdAt' in tweet_data:
                    try:
                        date_obj = datetime.datetime.strptime(
                            tweet_data['createdAt'],
                            "%a %b %d %H:%M:%S %z %Y"
                        )
                        dated_tweets.append((tweet_data, date_obj))
                    except (ValueError, TypeError):
                        # If parsing fails, add with None date (will be at the end)
                        dated_tweets.append((tweet_data, None))
                else:
                    # No date field found
                    dated_tweets.append((tweet_data, None))
            
            # Sort by date, handling None dates
            tweets_to_process = [t[0] for t in sorted(
                dated_tweets,
                key=lambda x: (x[1] is None, x[1])  # None values go to the end
            )]
            
            print(f"Sorted {len(tweets_to_process)} tweets by date")
        except Exception as e:
            print(f"Warning: Failed to sort tweets by date: {str(e)}")
            print("Will process tweets in their original order")
        
        if dry_run:
            print("DRY RUN MODE: Tweets will not actually be sent to Telegram")
        
        # Process each tweet
        successful = 0
        failed = 0
        
        for i, tweet_data in enumerate(tweets_to_process):
            current_idx = start_idx + i + 1
            try:
                # Parse the tweet
                tweet = Tweet.parse_obj(tweet_data)
                
                # Get tweet info for logging
                tweet_id = tweet.id or f"unknown-{i}"
                tweet_text = tweet.text or "(No text)"
                
                # Format tweet for display
                print(f"Tweet {current_idx}/{end_idx}: {tweet_id}")
                
                # Get the appropriate character for this tweet
                tweet_character = None
                
                # If a forced character was specified, use that
                if forced_character_obj:
                    tweet_character = forced_character_obj
                    character_name = character
                # Otherwise, try to match by username
                elif tweet.author and tweet.author.userName:
                    try:
                        tweet_character = config.characters[tweet.author.userName]
                        character_name = tweet_character.name
                        print(f"  Matched to character: {character_name} by username @{tweet.author.userName}")
                    except (KeyError, AttributeError):
                        print(f"  No matching character for @{tweet.author.userName}")
                
                # Always translate the tweet
                original_text = tweet_text
                translated_text = None
                
                if original_text:
                    try:
                        print(f"  Translating to Korean...")
                        translated_text = await translate(original_text)
                        print(f"  Translation successful")
                    except TranslationError as e:
                        print(f"  ⚠️ Translation error: {str(e)}")
                    except Exception as e:
                        print(f"  ⚠️ Unexpected error during translation: {str(e)}")
                
                # In dry run mode, just print the tweet details
                if dry_run:
                    if tweet.author:
                        print(f"  Author: {tweet.author.name} (@{tweet.author.userName})")
                    print(f"  Original: {original_text[:60]}..." if len(original_text) > 60 else f"  Original: {original_text}")
                    
                    if translated_text:
                        print(f"  Translated: {translated_text[:60]}..." if len(translated_text) > 60 else f"  Translated: {translated_text}")
                    
                    if tweet_character:
                        print(f"  Would send as: {tweet_character.name}")
                    else:
                        print(f"  No matching character found - would skip")
                    
                    # Count as successful in dry run only if we found a character
                    if tweet_character:
                        successful += 1
                    continue
                
                # Skip if no matching character found
                if not tweet_character:
                    print(f"  ✗ Skipped - no matching character found")
                    failed += 1
                    continue
                
                # Format and send the tweet
                if translated_text:
                    # Create a copy of the tweet with translated text
                    tweet_dict = tweet.dict()
                    tweet_dict["text"] = translated_text
                    translated_tweet = Tweet.parse_obj(tweet_dict)
                    formatted_message = format_tweet_for_telegram(translated_tweet)
                else:
                    formatted_message = format_tweet_for_telegram(tweet)
                
                try:
                    await send_telegram_message(tweet_character, formatted_message)
                    
                    if translated_text:
                        print(f"  ✓ Sent translated tweet to Telegram as {character_name}")
                    else:
                        print(f"  ✓ Sent original tweet to Telegram as {character_name}")
                except Exception as e:
                    # Error notification is already sent by send_telegram_message
                    print(f"  ✗ Failed to send tweet to Telegram: {str(e)}")
                    
                successful += 1
                
            except Exception as e:
                print(f"  ✗ Error processing tweet {current_idx}: {str(e)}")
                failed += 1
        
        # Print summary
        print(f"\nProcessed {count_to_process} tweets from {file_path}")
        
        if dry_run:
            if character:
                print(f"DRY RUN SUMMARY: Would have sent {successful} tweets as {character}")
            else:
                print(f"DRY RUN SUMMARY: Would have sent {successful} tweets via character auto-matching")
        else:
            if character:
                print(f"Successfully sent {successful} tweets to Telegram as {character}")
            else:
                print(f"Successfully sent {successful} tweets to Telegram via character auto-matching")
        
        skipped = failed
        if not character:
            print(f"Skipped {skipped} tweets (no matching character found)")
        elif failed > 0:
            print(f"Failed to process {failed} tweets")
    
    except Exception as e:
        print(f"Error: {str(e)}")

async def cmd_show_config(args):
    """
    Display the current configuration settings.
    
    Args:
        args: Command-line arguments after the subcommand
    """
    import config
    
    # Check if help is requested
    if args and args[0] in ['-h', '--help']:
        print("Usage: show-config")
        print("\nDescription:")
        print("  Display the current configuration settings, including API endpoints and model details.")
        print("  This can be helpful for debugging or confirming your environment is set up correctly.")
        return
    
    print("Current Configuration Settings:")
    print("==============================")
    
    # Translation settings
    print("\nTranslation:")
    print(f"  Model: {config.common.TRANSLATION_MODEL}")
    print(f"  Default model: {config.common.DEFAULT_TRANSLATION_MODEL}")
    print(f"  Using custom model: {'Yes' if config.common.TRANSLATION_MODEL != config.common.DEFAULT_TRANSLATION_MODEL else 'No'}")
    
    # API endpoints
    print("\nAPI Endpoints:")
    print(f"  Twitter API base URL: {config.common.TWITTER_API_BASE_URL}")
    print(f"  Twitter search endpoint: {config.common.TWITTER_SEARCH_ENDPOINT}")
    
    # Check environment variables (without showing full values)
    print("\nAPI Keys (Status):")
    print(f"  ANTHROPIC_API_KEY: {'Configured' if config.common.ANTHROPIC_API_KEY else 'Not set'}")
    print(f"  TWITTER_API_KEY: {'Configured' if config.common.TWITTER_API_KEY else 'Not set'}")
    
    # Telegram settings
    print("\nTelegram:")
    print(f"  Primary chat ID: {'Configured' if config.common.TELEGRAM_CHAT_ID else 'Not set'}")
    
    # Characters
    print("\nConfigured Characters:")
    for name in sorted(config.characters._character_config.keys()):
        char = config.characters._character_config[name]
        print(f"  - {name.capitalize()} (@{char.twitter_handle})")
        
    print("\nNote: To change the translation model, set the TRANSLATION_MODEL environment variable.")



async def cmd_test_error_logger(args):
    """
    Test the error logger by sending a test message to Telegram.
    """
    import config
    from logging_handlers import TelegramLogHandler
    import time
    
    # Check if help is requested
    if args and args[0] in ['-h', '--help']:
        print("Usage: test-error-logger [message]")
        print("\nOptions:")
        print("  message        Optional custom message to send (default: test message)")
        print("\nExamples:")
        print("  test-error-logger")
        print("  test-error-logger 'Custom test message'")
        return
    
    # Check if error logger is configured
    if not config.common.TELEGRAM_ERROR_BOT_TOKEN or not config.common.TELEGRAM_ERROR_CHAT_ID:
        print("Error: Telegram error logger is not configured")
        print("Please set TELEGRAM_ERROR_BOT_TOKEN and TELEGRAM_ERROR_CHAT_ID environment variables")
        return
    
    # Get custom message if provided
    message = " ".join(args) if args else "This is a test error message"
    
    print(f"Sending test error message to Telegram: '{message}'")
    
    # Create the handler directly
    handler = TelegramLogHandler(
        config.common.TELEGRAM_ERROR_BOT_TOKEN,
        config.common.TELEGRAM_ERROR_CHAT_ID,
        level=logging.ERROR
    )
    
    # Format a message for Telegram directly
    formatted_message = f"🧪 TEST ALERT: {message}"
    
    # Send directly using the handler's async method
    await handler._async_send(formatted_message)
    
    print("Test error message sent to Telegram")
    print(f"Bot token: {config.common.TELEGRAM_ERROR_BOT_TOKEN[:5]}...{config.common.TELEGRAM_ERROR_BOT_TOKEN[-5:]}")
    print(f"Chat ID: {config.common.TELEGRAM_ERROR_CHAT_ID}")


async def cmd_test_exception(args):
    """
    Test the error logger by raising an exception that should be logged.
    """
    import config
    from logging_handlers import TelegramLogHandler
    import time
    import socket
    import traceback
    
    # Check if help is requested
    if args and args[0] in ['-h', '--help']:
        print("Usage: test-exception [message]")
        print("\nOptions:")
        print("  message        Optional custom message to include in the exception (default: test exception)")
        print("\nExamples:")
        print("  test-exception")
        print("  test-exception 'Database connection failed'")
        return
    
    # Check if error logger is configured
    if not config.common.TELEGRAM_ERROR_BOT_TOKEN or not config.common.TELEGRAM_ERROR_CHAT_ID:
        print("Error: Telegram error logger is not configured")
        print("Please set TELEGRAM_ERROR_BOT_TOKEN and TELEGRAM_ERROR_CHAT_ID environment variables")
        return
    
    # Get custom message if provided
    message = " ".join(args) if args else "Test exception for error logging"
    
    print(f"Raising a test exception: '{message}'")
    print("This exception should be logged and sent to Telegram.")
    
    # Create the handler directly
    handler = TelegramLogHandler(
        config.common.TELEGRAM_ERROR_BOT_TOKEN,
        config.common.TELEGRAM_ERROR_CHAT_ID,
        level=logging.ERROR
    )
    
    # Now raise an exception that should be caught and logged
    try:
        # Simulate a division by zero error
        result = 1 / 0
    except Exception as e:
        # Get the traceback information
        exc_traceback = traceback.format_exc()
        
        # Log the exception with the message
        logger.error(f"{message}: {str(e)}", exc_info=True)
        
        # Format a message for Telegram directly
        hostname = socket.gethostname()
        telegram_message = f"🚨 *Test Error on {hostname}*\n\n"
        telegram_message += f"```\n{message}: {str(e)}\n\n{exc_traceback}\n```"
        
        # Send directly using the handler's async method
        print("Sending error directly to Telegram...")
        await handler._async_send(telegram_message)
        
        print("Exception raised and test message sent. Check your Telegram.")
        
        # Return to avoid propagating the exception
        return


async def cmd_test_translation_retry(args):
    """
    Test the translation retry mechanism with actual API calls.
    """
    from translate import translate, TranslationError
    
    # Check if help is requested
    if args and args[0] in ['-h', '--help']:
        print("Usage: test-translation-retry [text]")
        print("\nOptions:")
        print("  text           Optional text to translate (default: test message)")
        print("\nExamples:")
        print("  test-translation-retry")
        print("  test-translation-retry 'こんにちは'")
        return
    
    # Create a test message if not provided
    text = " ".join(args) if args else "こんにちは、世界！"
    
    print(f"Testing translation retry mechanism with text: '{text}'")
    print("Note: This test will make a real API call to Anthropic.")
    print("If you encounter a rate limit error, the retry mechanism will be tested.")
    print("Otherwise, a successful translation indicates the functionality is working correctly.")
    
    try:
        # Call the real translation function
        result = await translate(text)
        print("✓ Translation successful:")
        print(f"Translated text: {result}")
    except TranslationError as e:
        print(f"✗ Translation failed even with retry: {str(e)}")
        
    print("\nTesting complete. The retry mechanism will automatically handle rate limit errors (HTTP 429)")
    print("by using exponential backoff and retrying up to 3 times by default.")

async def main_cli():
    """Command-line interface for the Twitter to Telegram tool."""
    # List of available commands
    commands = {
        "fetch-and-send": cmd_fetch_and_send,
        "dump-tweets": cmd_dump_tweets,
        "send-from-file": cmd_send_from_file,
        "send-admin-notification": cmd_send_admin_notification,
        "test-error-logger": cmd_test_error_logger,
        "test-exception": cmd_test_exception,
        "show-config": cmd_show_config,
        "test-translation-retry": cmd_test_translation_retry,
        # Add more commands here as needed
    }
    
    # No arguments or help flag
    if len(sys.argv) < 2 or sys.argv[1] in ['-h', '--help']:
        print("Twitter to Telegram CLI")
        print("\nUsage: python cli.py <command> [options]")
        print("\nAvailable commands:")
        print("  fetch-and-send          Fetch tweets and forward them to Telegram")
        print("  dump-tweets             Fetch tweets and save them to a JSON file")
        print("  send-from-file          Send tweets from a JSON file to Telegram")
        print("  send-admin-notification Send an admin notification to Telegram as Mai")
        print("  test-error-logger       Test the error logging system by sending a test message")
        print("  test-exception          Test the error logger with a simulated exception") 
        print("  test-translation-retry  Test the translation retry mechanism")
        print("  show-config             Display current configuration settings")
        # Add more command descriptions here
        print("\nFor help on a specific command, run:")
        print("  python cli.py <command> --help")
        return
    
    # Get the command
    command = sys.argv[1]
    
    # Remove the command from arguments
    command_args = sys.argv[2:]
    
    if command in commands:
        # Execute the command
        await commands[command](command_args)
    else:
        print(f"Unknown command: {command}")
        print("Available commands: " + ", ".join(commands.keys()))


if __name__ == "__main__":
    asyncio.run(main_cli())
