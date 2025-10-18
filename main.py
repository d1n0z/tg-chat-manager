import asyncio


if __name__ == "__main__":
    from src.main import main

    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
