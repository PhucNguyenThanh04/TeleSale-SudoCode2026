import json
from app.mcp_servers.mcp_knowledge.schemas import PolicyRuntimeConfig


def load_policy_config(settings):
    if not settings.knowledge_policy_config_file:
        raise ValueError('KNOWLEDGE_POLICY_CONFIG_FILE required')
    return PolicyRuntimeConfig.model_validate(json.loads(settings.knowledge_policy_config_file.read_text(encoding='utf-8')))
