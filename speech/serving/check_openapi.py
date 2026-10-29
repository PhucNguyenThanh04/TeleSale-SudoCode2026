"""Check the deployed public Swagger contract without credentials."""

import json
from urllib.request import ProxyHandler, Request, build_opener


BASE = "https://sudoapi.ktoxz.id.vn"


def get(path):
    request = Request(BASE + path, headers={"User-Agent": "TeleSaleSpeechHealth/0.1"})
    with build_opener(ProxyHandler({})).open(request, timeout=20) as response:
        return response.read()


if __name__ == "__main__":
    assert b"swagger-ui" in get("/docs")
    schema = json.loads(get("/openapi.json"))
    assert not schema.get("security")
    assert not schema.get("components", {}).get("securitySchemes")
    paths = schema["paths"]
    assert "audio/wav" in paths["/v1/speech/transcribe"]["post"]["requestBody"]["content"]
    assert "audio/wav" in paths["/v1/speech/synthesize"]["post"]["responses"]["200"]["content"]
    assert "/v1/speech/synthesize/sequence" in paths
    assert "text/event-stream" in paths["/v1/speech/synthesize/stream"]["post"]["responses"]["200"]["content"]
    print(json.dumps({"docs": "public", "title": schema["info"]["title"], "api_paths": list(paths)}))
