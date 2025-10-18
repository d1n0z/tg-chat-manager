import asyncio
from src.main import main


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
