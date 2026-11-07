"""Render upstream native profiles; schemas and model metadata come from the pinned old roster."""

import json
import sys
from pathlib import Path

route = json.loads((Path(__file__).parent / "routing.json").read_text())
prefix = Path(sys.argv[1])
profiles = prefix / "profiles"
base_url, model = route["base_url"], route["combo"]


def write(relative: str, data: object) -> None:
    path = profiles / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSON is also valid YAML for the upstream OMP/Hermes YAML readers.
    path.write_text(json.dumps(data, indent=2) + "\n")


metadata = {
    "id": model,
    "name": "Sextant GPT lane",
    "reasoning": True,
    "input": ["text"],
    "contextWindow": 200000,
    "maxTokens": 32000,
}
provider = {
    "baseUrl": base_url,
    "apiKey": "${OMNIROUTE_API_KEY}",
    "api": "openai-completions",
    "authHeader": True,
    "models": [{**metadata, "thinkingLevelMap": {"max": "max"}}],
}
write("pi/models.json", {"providers": {"omniroute": provider}})
write(
    "pi/settings.json",
    {
        "defaultProvider": "omniroute",
        "defaultModel": model,
        "defaultThinkingLevel": "max",
        "enableInstallTelemetry": False,
        "enableAnalytics": False,
    },
)
write(
    "omp/models.yml",
    {"providers": {"omniroute": {**provider, "apiKey": "OMNIROUTE_API_KEY", "models": [metadata]}}},
)
write(
    "omp/config.yml",
    {
        "tools": {"approvalMode": "yolo"},
        "enabledProviders": ["omniroute"],
        "startup": {"checkUpdate": False, "setupWizard": False, "quiet": True},
        "defaultThinkingLevel": "max",
        "modelRoles": {
            role: "omniroute/" + model
            for role in (
                "default",
                "smol",
                "slow",
                "plan",
                "commit",
                "task",
                "vision",
                "tiny",
                "memory",
                "advisor",
            )
        },
    },
)
write(
    "opencode.json",
    {
        "model": "omniroute/" + model,
        "provider": {
            "omniroute": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Sextant OmniRoute",
                "options": {"baseURL": base_url, "apiKey": "{env:OMNIROUTE_API_KEY}"},
                "models": {
                    model: {
                        "name": "Sextant GPT lane",
                        "reasoning": True,
                        "limit": {"context": 200000, "output": 32000},
                        "options": {"reasoningEffort": "max"},
                    }
                },
            }
        },
    },
)
write(
    "hermes/config.yaml",
    {
        "model": {
            "provider": "custom",
            "default": model,
            "base_url": base_url,
            "key_env": "OMNIROUTE_API_KEY",
            "api_mode": "chat_completions",
        },
        "auth": {"adopt_external_logins": False},
        "agent": {"reasoning_effort": "max"},
        "updates": {"check": False},
        "fallback_providers": [],
    },
)
write(
    "openhands.json",
    {
        "model": "openai/" + model,
        "base_url": base_url,
        "reasoning_effort": "max",
        "auth_type": "api_key",
        "api_mode": "chat",
    },
)
