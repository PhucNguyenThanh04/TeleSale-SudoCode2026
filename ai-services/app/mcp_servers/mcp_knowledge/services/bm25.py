from collections import Counter
import math
import re
import unicodedata
from app.knowledge.schemas import digest

TOKENIZER_VERSION = 'unicode-nfc-v1'
_TERMS = re.compile(r'[^\W_]+(?:[-./][^\W_]+)*', re.UNICODE)


def tokenize(text):
    return _TERMS.findall(unicodedata.normalize('NFC', text).casefold())


def build_bm25_artifact(texts, config):
    documents = [tokenize(text) for text in texts]
    if not documents or any(not terms for terms in documents):
        raise ValueError('Nonempty BM25 documents required')
    vocabulary = {term:index for index,term in enumerate(sorted({t for terms in documents for t in terms}))}
    artifact = {'tokenizer':config.bm25_tokenizer, 'vocabulary':vocabulary,
        'documents':len(documents), 'avgdl':sum(map(len, documents))/len(documents),
        'k1':config.bm25_k1, 'b':config.bm25_b}
    return artifact | {'hash':digest(artifact)}


class BM25Encoder:
    def __init__(self, artifact):
        body = {key:value for key,value in artifact.items() if key != 'hash'}
        if (digest(body) != artifact.get('hash') or body.get('tokenizer') != TOKENIZER_VERSION
                or not isinstance(body.get('documents'), int) or body['documents'] <= 0
                or not math.isfinite(body.get('avgdl', 0)) or body['avgdl'] <= 0
                or not math.isfinite(body.get('k1', 0)) or body['k1'] <= 0
                or not math.isfinite(body.get('b', -1)) or not 0 <= body['b'] <= 1):
            raise ValueError('BM25 artifact corrupt or incompatible')
        vocab = body.get('vocabulary')
        if not isinstance(vocab, dict) or vocab != {term:i for i,term in enumerate(sorted(vocab))}:
            raise ValueError('BM25 vocabulary mismatch')
        self.artifact = artifact
        self.vocabulary = vocab

    def encode_query(self, text):
        indices = sorted({self.vocabulary[t] for t in tokenize(text) if t in self.vocabulary})
        return indices, [1.0]*len(indices)

    def encode_document(self, text):
        terms = tokenize(text)
        counts = Counter(terms)
        if not terms or any(t not in self.vocabulary for t in terms):
            raise ValueError('Document differs from BM25 corpus')
        k1, b, avgdl = (self.artifact[key] for key in ('k1','b','avgdl'))
        pairs = sorted((self.vocabulary[t], tf*(k1+1)/(tf+k1*(1-b+b*len(terms)/avgdl)))
                       for t,tf in counts.items())
        return [i for i,_ in pairs], [v for _,v in pairs]


def document_text(chunk):
    from app.mcp_servers.mcp_shared.pii import mask_pii
    return mask_pii(chunk.content+'\n'+'\n'.join(chunk.search_aliases))
