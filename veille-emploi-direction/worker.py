"""Worker entrypoint for the veille-emploi-direction workflow."""
import asyncio

from mistralai.workflows import run_worker

from src.workflows import veille


async def main() -> None:
    await run_worker([veille])


if __name__ == "__main__":
    asyncio.run(main())
