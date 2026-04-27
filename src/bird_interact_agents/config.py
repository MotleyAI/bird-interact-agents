"""Centralized configuration via environment variables and .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Path to the cloned BIRD-Interact repository
    bird_interact_root: str = ""

    # Path to mini_interact.jsonl (with ground truth merged)
    data_path: str = ""

    # Path to mini-interact/ directory containing SQLite DBs
    db_path: str = ""

    # User simulator LLM model (LiteLLM format)
    user_sim_model: str = "anthropic/claude-haiku-4-5-20251001"

    # User simulator prompt version: "v1" or "v2"
    user_sim_prompt_version: str = "v2"

    model_config = {"env_prefix": "BIRD_", "env_file": ".env", "extra": "ignore"}

    @property
    def mini_interact_agent_root(self) -> Path:
        """Path to the mini_interact_agent directory within BIRD-Interact."""
        return (
            Path(self.bird_interact_root)
            / "mini_interact"
            / "knowledge_based"
            / "mini_interact_agent"
        )


settings = Settings()
