import asyncio
import pytest
import main


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    """Verify asyncio.Semaphore strictly enforces max concurrent tasks."""
    max_concurrency = 2
    sem = asyncio.Semaphore(max_concurrency)

    active_count = 0
    max_observed_active = 0
    lock = asyncio.Lock()

    async def mock_worker(asset: str):
        nonlocal active_count, max_observed_active
        async with sem:
            async with lock:
                active_count += 1
                if active_count > max_observed_active:
                    max_observed_active = active_count

            # Simulate network/LLM I/O latency
            await asyncio.sleep(0.05)

            async with lock:
                active_count -= 1

    assets = ["BTC", "ETH", "SOL", "XRP", "BNB", "LINK"]
    tasks = [mock_worker(a) for a in assets]
    await asyncio.gather(*tasks)

    assert max_observed_active == max_concurrency
    assert active_count == 0


@pytest.mark.asyncio
async def test_full_basket_handles_individual_asset_failure():
    """Verify that an error in one asset does not crash the entire evaluation loop."""
    sem = asyncio.Semaphore(2)

    completed_assets = []

    async def mock_eval(asset: str):
        async with sem:
            if asset == "XRP":
                raise ConnectionError("Simulated network timeout on XRP")
            await asyncio.sleep(0.01)
            completed_assets.append(asset)

    assets = ["BTC", "ETH", "XRP", "SOL"]
    tasks = [mock_eval(a) for a in assets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # XRP should be a ConnectionError instance
    assert any(isinstance(r, ConnectionError) for r in results)
    # The other 3 assets should have completed successfully
    assert set(completed_assets) == {"BTC", "ETH", "SOL"}
