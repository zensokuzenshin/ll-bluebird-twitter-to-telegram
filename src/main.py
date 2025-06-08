import sys
import uvicorn


def print_usage():
    """Print usage information for the script."""
    print("Twitter Forward to Telegram")
    print("\nUsage:")
    print("  python main.py [server|cli] [subcommand] [options]")
    print("\nModes:")
    print("  server                Run the webhook server")
    print("  cli <subcommand>      Run the command-line interface")
    print("\nCLI Subcommands:")
    print("  fetch-and-send        Fetch tweets and forward them to Telegram")
    print("  dump-tweets           Fetch tweets and save them to a JSON file")
    print("  send-from-file        Send tweets from a JSON file to Telegram")
    print("\nExamples:")
    print(
        "  python main.py server                                       # Run the webhook server"
    )
    print(
        "  python main.py cli fetch-and-send --limit=5                 # Fetch tweets and forward to Telegram"
    )
    print(
        "  python main.py cli dump-tweets --file=tweets.json           # Fetch tweets and save to file"
    )
    print(
        "  python main.py cli send-from-file --file=tweets.json                   # Send tweets with auto-matching"
    )
    print("\nFor more detailed help on CLI options, run:")
    print("  python main.py cli                   # Show available CLI subcommands")
    print(
        "  python main.py cli fetch-and-send    # Show options for the fetch-and-send subcommand"
    )
    print(
        "  python main.py cli dump-tweets       # Show options for the dump-tweets subcommand"
    )
    print(
        "  python main.py cli send-from-file    # Show options for the send-from-file subcommand"
    )


if __name__ == "__main__":
    # Check if a mode is specified
    if len(sys.argv) < 2:
        # No mode specified, default to server
        from server import app

        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        mode = sys.argv[1].lower()

        if mode == "server":
            # Server mode
            from server import app

            uvicorn.run(app, host="0.0.0.0", port=8000)

        elif mode == "cli":
            # CLI mode - remove the mode argument for the CLI script
            sys.argv.pop(1)
            from cli import main_cli
            import asyncio

            asyncio.run(main_cli())

        else:
            # Unknown mode
            print(f"Unknown mode: {mode}")
            print_usage()
            sys.exit(1)
