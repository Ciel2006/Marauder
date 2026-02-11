"""AI client wrapper for OpenAI-compatible APIs."""
from openai import OpenAI
import httpx


def create_client(base_url: str, api_key: str) -> OpenAI:
    """Create an OpenAI-compatible client with generous timeouts."""
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=httpx.Timeout(300.0, connect=30.0),
    )


def test_connection(client: OpenAI, model: str) -> bool:
    """Test the API connection with a simple prompt."""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say 'ok' if you can read this."}],
            max_tokens=10,
            timeout=httpx.Timeout(60.0, connect=15.0),
        )
        text = resp.choices[0].message.content or ""
        return len(text.strip()) > 0
    except Exception as e:
        print(f"  ❌ Connection failed: {e}")
        return False
