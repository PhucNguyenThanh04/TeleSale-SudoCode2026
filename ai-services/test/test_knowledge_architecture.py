import ast
import importlib
from pathlib import Path


def test_mcp_components_follow_existing_server_layers():
    expected = {
        'app.mcp_servers.mcp_knowledge.schemas': 'PolicySearchInput',
        'app.mcp_servers.mcp_knowledge.repos.postgres': 'PolicyRepository',
        'app.mcp_servers.mcp_knowledge.repos.qdrant': 'HybridPolicyIndex',
        'app.mcp_servers.mcp_knowledge.services.knowledge': 'PolicySearchService',
        'app.mcp_servers.mcp_knowledge.services.embedding': 'PolicyEncoder',
        'app.mcp_servers.mcp_knowledge.config': 'load_policy_config',
        'app.mcp_servers.mcp_knowledge.tools.handlers': 'create_server',
    }
    for module, symbol in expected.items():
        value = getattr(importlib.import_module(module), symbol)
        assert value.__module__ == module


def test_shared_knowledge_components_have_explicit_owners():
    expected = {
        'app.knowledge.repos.postgres': 'KnowledgeRepo',
        'app.knowledge.events.ingest': 'record_event',
        'app.knowledge.events.worker': 'process_one',
        'app.knowledge.services.lifecycle': 'command',
        'app.knowledge.services.publish': 'build_policy_release',
        'app.knowledge.policy.source': 'parse_policy_sources',
        'app.knowledge.policy.rules': 'apply_policy_rules',
        'app.knowledge.schemas': 'SourceChunk',
    }
    for module, symbol in expected.items():
        assert getattr(importlib.import_module(module), symbol).__module__ == module
    assert callable(importlib.import_module('app.knowledge.events.worker').main)
    assert callable(importlib.import_module('app.knowledge.cli').main)


def test_shared_code_never_imports_mcp_server_entrypoint():
    root = Path(__file__).resolve().parents[1] / 'app' / 'knowledge'
    for path in root.rglob('*.py'):
        if '__pycache__' in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.module != 'app.mcp_servers.mcp_knowledge.server', path
