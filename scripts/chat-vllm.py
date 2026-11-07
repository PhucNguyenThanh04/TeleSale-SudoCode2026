#!/usr/bin/env python3
"""Chat with the local vLLM server using only Python's standard library."""

import json
import urllib.error
import urllib.request


def main():
    messages = []
    print("Chat Qwen3 local | /clear: xóa lịch sử | /exit: thoát")
    while True:
        try:
            question = input("\nBạn: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question == "/exit":
            break
        if question == "/clear":
            messages.clear()
            print("Đã xóa lịch sử.")
            continue
        if not question:
            continue

        pending = messages + [{"role": "user", "content": question}]
        request = urllib.request.Request(
            "http://127.0.0.1:8002/v1/chat/completions",
            data=json.dumps({
                "model": "Qwen/Qwen3-0.6B",
                "messages": pending,
                "max_tokens": 256,
                "temperature": 0.7,
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                answer = json.load(response)["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as error:
            print(f"Lỗi API {error.code}: {error.read().decode()}")
            print("Nếu lịch sử vượt context 4096 token, gõ /clear để bắt đầu lại.")
            continue
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"Không gọi được vLLM: {error}")
            print("Kiểm tra server: systemctl --user status telesale-vllm")
            continue
        except KeyboardInterrupt:
            print()
            break
        print(f"AI: {answer}")
        messages = pending + [{"role": "assistant", "content": answer}]


if __name__ == "__main__":
    main()
