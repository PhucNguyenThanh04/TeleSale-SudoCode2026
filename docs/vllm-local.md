# Local vLLM on RTX 3050 Laptop (4 GB)

The local model is `Qwen/Qwen3-0.6B`, served on the GPU with FP16 weights.
It leaves more room for vLLM and its KV cache than a 1.7B model with FP16
weights. This is a local development choice; telesale accuracy and reliable
tool selection have not been evaluated.

Configuration: 4096 tokens total input + output, one concurrent sequence,
80% GPU memory budget, eager execution, thinking disabled, Hermes tool parser.
Other GPU workloads, including speech models, may require stopping this server.

## Install and run

From the repository root, use a separate environment from the application:

```bash
uv python install 3.12
uv venv .venv-vllm --python 3.12 --managed-python
uv pip install --python .venv-vllm/bin/python 'vllm==0.33.0'
bash scripts/serve-vllm.sh
```

The first start downloads the model to the Hugging Face cache. The server binds
only to localhost and has no API authentication. Do not expose it publicly
without adding authentication.

To run in the background for the current user session (from the repository root):

```bash
systemd-run --user --unit=telesale-vllm --collect \
  --property="WorkingDirectory=$PWD" /bin/bash "$PWD/scripts/serve-vllm.sh"
systemctl --user status telesale-vllm
journalctl --user -u telesale-vllm -f
systemctl --user stop telesale-vllm
```

This transient service does not automatically start after a reboot. To start
again after stopping it, repeat the `systemd-run` command.

## Check the API

For an interactive terminal chat with conversation history:

```bash
python3 scripts/chat-vllm.py
```

Type `/clear` to reset history or `/exit` to quit. The server allows 4096 tokens
including history and the response; use `/clear` when the conversation fills it.

```bash
curl --fail http://127.0.0.1:8002/health
curl --fail http://127.0.0.1:8002/v1/models
curl --fail http://127.0.0.1:8002/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3-0.6B","messages":[{"role":"user","content":"Chào bạn, hãy giới thiệu bằng một câu tiếng Việt."}],"max_tokens":80}'
```

## Optional TeleSale connection

Set these values in the AI service's local environment, then restart that service:

```dotenv
LLM_BACKEND=local
LOCAL_LLM_BASE_URL=http://127.0.0.1:8002/v1
LOCAL_LLM_MODEL=Qwen/Qwen3-0.6B
LOCAL_LLM_API_KEY=local-vllm
```

`local-vllm` is a placeholder required by the client, not a server credential.
Existing application credentials and model settings are not changed by the
launcher. Long agent prompts must fit the server's 4096-token context window.
Set `LLM_BACKEND=api` to return to the saved API profile. For the separately
served `Qwen/Qwen2.5-3B-Instruct-AWQ` at port 8081, use that model ID and
`LOCAL_LLM_BASE_URL=http://localhost:8081/v1` instead. See
[the AI service switching instructions](../ai-services/README.md#switch-between-the-api-and-a-local-model)
for the Docker memory-worker address and restart steps. This launcher's
loopback-only bind is suitable for host clients; a Docker worker also needs a
server bind address it can reach.

References: [model card](https://huggingface.co/Qwen/Qwen3-0.6B),
[vLLM installation](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/),
[engine arguments](https://docs.vllm.ai/en/latest/configuration/engine_args/).
