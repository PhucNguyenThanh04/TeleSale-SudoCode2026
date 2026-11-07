"""Deterministic relevance ordering over already-authorized memory episodes."""
import re

from app.mcp_servers.mcp_shared.commerce_rules import _search_text


def resolved_episode_view(episodes: list[dict], evidence: list[dict]) -> list[dict]:
    """Keep accepted resolutions even when their session is outside the shortlist."""
    resolved = {entry['item_id']: entry for episode in evidence
                if episode.get('status', 'active') == 'active'
                for entry in episode.get('resolved_prior_items', [])
                if isinstance(entry, dict) and isinstance(entry.get('item_id'), str)}
    result = []
    for episode in episodes:
        matched, topics = set(), []
        for topic in episode.get('topics', []):
            items = []
            for item in topic.get('items', []):
                if isinstance(item, dict) and item.get('item_id') in resolved:
                    matched.add(item['item_id'])
                    item = {**item, 'status': 'resolved'}
                items.append(item)
            topics.append({**topic, 'items': items})
        if matched:
            existing = episode.get('resolved_prior_items', [])
            ids = {entry.get('item_id') for entry in existing if isinstance(entry, dict)}
            episode = {**episode, 'topics': topics, 'resolved_prior_items': [
                *existing, *(resolved[key] for key in sorted(matched - ids))]}
        result.append(episode)
    return result


def rank_episodes(episodes: list[dict], customer_text: str, limit: int) -> list[dict]:
    query = _search_text(customer_text)
    terms = {word for word in re.findall(r'[\w-]+', query) if len(word) > 2}

    def score(item):
        topics = [topic for topic in item.get('topics', []) if isinstance(topic, dict)]
        product_match = any(topic.get('scope_type') == 'product'
            and isinstance(topic.get('scope_id'), str) and topic['scope_id']
            and re.search(r'(?<![\w-])' + re.escape(_search_text(topic['scope_id'])) + r'(?![\w-])', query)
            for topic in topics)
        texts = [str(item.get('summary', ''))]
        open_blocker = False
        for topic in topics:
            texts.extend(str(topic.get(key, '')) for key in ('customer_goal', 'advice_given', 'next_step'))
            for entry in topic.get('items', []):
                if isinstance(entry, dict):
                    texts.append(str(entry.get('text', '')))
                    open_blocker |= entry.get('kind') == 'blocker' and entry.get('status') == 'open'
        words = set(re.findall(r'[\w-]+', _search_text(' '.join(texts))))
        return (bool(product_match), len(terms & words), open_blocker, str(item.get('on', '')))

    return sorted(episodes, key=score, reverse=True)[:limit]
