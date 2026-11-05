import math
import unicodedata
import pytest
from test_policy_embedding import runtime_config


def test_bm25_unicode_ids_and_artifact_order_are_stable():
    from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact, BM25Encoder
    texts=['bảo hành DT-OLD-03 SKU-123 30.000đ/chiều','đổi size']
    a=build_bm25_artifact(texts,runtime_config())
    assert a==build_bm25_artifact(list(reversed(texts)),runtime_config())
    encoder=BM25Encoder(a)
    assert encoder.encode_query('BẢO HÀNH')==encoder.encode_query(unicodedata.normalize('NFD','bảo hành'))
    assert encoder.encode_query('bao hanh') == ([],[])
    assert encoder.encode_query('DT-OLD-03')[0] and encoder.encode_query('SKU-123')[0]
    assert encoder.encode_query('outofvocabulary') == ([],[])


def test_bm25_document_weights_and_query_uniqueness():
    from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact, BM25Encoder
    artifact=build_bm25_artifact(['a a b','b'],runtime_config())
    encoder=BM25Encoder(artifact)
    indices,values=encoder.encode_document('a a b')
    assert values[indices.index(artifact['vocabulary']['a'])] == pytest.approx(2*2.2/(2+1.2*(.25+.75*3/2)))
    assert encoder.encode_query('a a') == encoder.encode_query('a')
    assert encoder.encode_query('a')[1]==[1.0]


def test_artifact_tampering_is_rejected():
    from app.mcp_servers.mcp_knowledge.services.bm25 import build_bm25_artifact, BM25Encoder
    artifact=build_bm25_artifact(['a b'],runtime_config())
    artifact['avgdl']=99
    with pytest.raises(ValueError): BM25Encoder(artifact)
    with pytest.raises(ValueError): build_bm25_artifact([],runtime_config())
