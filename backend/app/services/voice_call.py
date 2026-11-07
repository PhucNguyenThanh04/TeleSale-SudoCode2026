"""One temporary call: transport orchestration, with agent state owned by harness."""

import asyncio
import json
import logging
from contextlib import suppress
from uuid import UUID, uuid4

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.voice import End, PlaybackFinished, Start, parse_command
from app.services.voice_speech import INPUT_AUDIO, SpeechClient

logger = logging.getLogger(__name__)


class FatalCallError(Exception):
    pass


class VoiceCall:
    def __init__(self, browser: WebSocket, speech: SpeechClient, ai_http: httpx.AsyncClient,
                 start_timeout: float = 10):
        self.browser = browser
        self.speech = speech
        self.ai_http = ai_http
        self.start_timeout = start_timeout
        self.state = "initializing"
        self.start: Start | None = None
        self.session_id: str | None = None
        self.turn_id: str | None = None
        self.turn_ids: dict[str, str] = {}
        self.awaiting_playback = False
        self.socket = None
        self.front_task = None
        self.speech_task = None
        self.reply_task = None
        self.prepare_task = None
        self.memory_tasks = set()
        self.send_lock = asyncio.Lock()

    async def send(self, event: str, **fields):
        async with self.send_lock:
            await self.browser.send_json({"event": event, **fields})

    async def set_state(self, state: str):
        self.state = state
        logger.info("voice state=%s", state)
        await self.send("state", state=state)

    async def error(self, stage: str, code: str, fatal: bool, *, turn_id: str | None = None):
        logger.info("voice error stage=%s code=%s fatal=%s", stage, code, fatal)
        await self.send("error", stage=stage, code=code,
                        message=code.replace("_", " "), fatal=fatal,
                        turn_id=turn_id if turn_id is not None else self.turn_id)

    async def listen(self):
        try:
            self.socket = await self.speech.connect_listen()
        except Exception:
            await self.error("stt", "speech_unavailable", True)
            raise FatalCallError from None
        self.turn_ids.clear()
        self.speech_task = asyncio.create_task(self.socket.recv())

    async def stop_listening(self):
        if self.speech_task is not None:
            self.speech_task.cancel()
            await asyncio.gather(self.speech_task, return_exceptions=True)
            self.speech_task = None
        if self.socket is not None:
            socket, self.socket = self.socket, None
            await socket.close()

    async def prepare(self):
        try:
            response = await self.ai_http.post("/v1/chat/sessions/prepare", json={
                "session_id": self.session_id, "channel": self.start.channel,
                "channel_identity": self.start.channel_identity,
                "on": self.start.on.isoformat(),
            })
            response.raise_for_status()
            if str(UUID(response.json()["session_id"])) != self.session_id:
                raise ValueError("Harness changed prepared session")
        except Exception:
            await self.error("harness", "preparation_failed", True)
            raise FatalCallError from None

    async def track_memory(self, turn_id: str, client_msg_id: str, initial: dict):
        payload = {"session_id": self.session_id, "client_msg_id": client_msg_id,
                   "channel": self.start.channel, "channel_identity": self.start.channel_identity,
                   "on": self.start.on.isoformat()}
        update = initial
        try:
            async with asyncio.timeout(60):
                while True:
                    response = await self.ai_http.post("/v1/chat/turns/memory", json=payload)
                    response.raise_for_status()
                    result = response.json()
                    if (result["session_id"] != payload["session_id"]
                            or result["client_msg_id"] != client_msg_id):
                        raise ValueError("Memory status changed turn")
                    update = result["memory_update"]
                    if update["status"] != "pending":
                        break
                    await asyncio.sleep(1)
        except TimeoutError:
            update = {"turn_saved": initial["turn_saved"], "status": "pending", "changes": []}
        except Exception:
            update = {"turn_saved": initial["turn_saved"], "status": "unavailable", "changes": []}
        try:
            await self.send("memory_update", turn_id=turn_id, client_msg_id=client_msg_id,
                            memory_update=update, tracking_finished=True)
        except Exception:
            pass  # The call may have disconnected while the status request finished.

    async def reply(self, text: str):
        if self.prepare_task is not None:
            await self.prepare_task
        request = {
            "client_msg_id": str(uuid4()),
            "channel": self.start.channel,
            "channel_identity": self.start.channel_identity,
            "on": self.start.on.isoformat(),
            "text": text,
            "input_mode": "asr_transcript",
        }
        if self.session_id is not None:
            request["session_id"] = self.session_id
        try:
            response = await self.ai_http.post("/v1/chat/turns", json=request)
            response.raise_for_status()
            result = response.json()
            # A malformed response must not start a new session on the next turn.
            session_id = str(UUID(result["session_id"]))
            if self.session_id is not None and session_id != self.session_id:
                raise ValueError("Harness changed session")
            agent_text = result["agent_text"]
            if not isinstance(agent_text, str) or not agent_text.strip():
                raise ValueError("Harness returned no answer")
            self.session_id = session_id
        except Exception:
            await self.error("harness", "harness_failed", True)
            raise FatalCallError from None

        await self.send("agent_reply", turn_id=self.turn_id, session_id=self.session_id,
                        agent_text=agent_text, call_brief=result.get("call_brief"),
                        needs_handoff=result.get("needs_handoff", False),
                        handoff_ticket_id=result.get("handoff_ticket_id"),
                        memory_update=result.get("memory_update"))
        memory_update = result.get("memory_update")
        if memory_update and memory_update.get("status") == "pending":
            task = asyncio.create_task(self.track_memory(
                self.turn_id, request["client_msg_id"], memory_update))
            self.memory_tasks.add(task)
            task.add_done_callback(self.memory_tasks.discard)
        await self.set_state("speaking")
        try:
            index = 0
            async for event in self.speech.stream_tts(agent_text):
                if event["event"] == "audio_chunk":
                    await self.send("audio", turn_id=self.turn_id, index=index,
                                    segment_index=event["index"],
                                    format={"encoding": "pcm_s16le", "sample_rate": event["sample_rate"],
                                            "channels": 1},
                                    audio_base64=event["pcm16_base64"])
                    index += 1
                elif event["event"] == "segment_end":
                    await self.send("audio_segment_end", turn_id=self.turn_id,
                                    segment_index=event["index"], pause_ms=200)
            # Set before sending the completion event so an immediate ack is valid.
            self.awaiting_playback = True
            await self.send("audio_complete", turn_id=self.turn_id)
        except Exception:
            self.awaiting_playback = True
            await self.error("tts", "tts_failed", False)

    async def on_speech(self, event: dict):
        name = event["event"]
        if name == "error":
            fatal = event.get("fatal", True)
            code = event.get("code")
            known = {"transcription_failed", "overloaded", "service_unavailable",
                     "invalid_message", "audio_too_large"}
            failed_turn = self.turn_ids.pop(event.get("turn_id"), None)
            await self.error("stt", code if code in known else "speech_failed", fatal,
                             turn_id=failed_turn)
            if fatal:
                raise FatalCallError
            return
        if name not in {"speech_started", "speech_ended", "transcript_final"}:
            return
        source_id = event["turn_id"]
        turn_id = self.turn_ids.setdefault(source_id, str(uuid4()))
        if name == "transcript_final":
            text = event["text"]
            if not isinstance(text, str):
                raise ValueError("Invalid transcript")
            if not text.strip():
                self.turn_ids.pop(source_id, None)
                return
            self.turn_id = turn_id
            await self.set_state("processing")
            await self.send("transcript_final", turn_id=turn_id, text=text)
            # Discard pending speech jobs/audio; a fresh connection on resume
            # prevents delayed finals from being mistaken for a new user turn.
            await self.stop_listening()
            self.reply_task = asyncio.create_task(self.reply(text))
        else:
            fields = {"reason": event["reason"]} if name == "speech_ended" else {}
            await self.send(name, turn_id=turn_id, **fields)

    async def on_frontend(self, message: dict) -> bool:
        if message["type"] == "websocket.disconnect":
            return False
        audio = message.get("bytes")
        if audio is not None:
            if len(audio) > 32000:
                await self.error("protocol", "audio_too_large", True)
                return False
            if self.state == "listening":
                try:
                    await self.socket.send(audio)
                except Exception:
                    await self.error("stt", "speech_disconnected", True)
                    return False
            return True
        try:
            command = parse_command(json.loads(message.get("text", "")))
        except (ValidationError, ValueError, TypeError):
            await self.error("protocol", "invalid_command", False)
            return True
        if isinstance(command, End):
            return False
        if isinstance(command, PlaybackFinished):
            if not self.awaiting_playback or command.turn_id != self.turn_id:
                await self.error("protocol", "unexpected_playback", False)
                return True
            self.awaiting_playback = False
            # reply() has finished all speech work before accepting this ack.
            if self.reply_task is not None:
                await self.reply_task
                self.reply_task = None
            self.turn_id = None
            await self.listen()
            await self.set_state("listening")
        else:
            await self.error("protocol", "already_started", False)
        return True

    async def run(self):
        try:
            async with asyncio.timeout(self.start_timeout):
                first = await self.browser.receive()
            if first["type"] == "websocket.disconnect":
                return
            try:
                start = parse_command(json.loads(first.get("text", "")))
                if not isinstance(start, Start):
                    raise ValueError("Expected start")
            except (ValidationError, ValueError, TypeError):
                await self.error("protocol", "start_required", True)
                return
            self.start = start
            self.session_id = str(uuid4())
            self.prepare_task = asyncio.create_task(self.prepare())
            await self.listen()
            await self.send("ready", audio=INPUT_AUDIO)
            await self.set_state("listening")
            self.front_task = asyncio.create_task(self.browser.receive())
            while True:
                tasks = [t for t in (self.front_task, self.speech_task, self.reply_task,
                                     self.prepare_task) if t is not None]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if self.front_task in done:
                    if not await self.on_frontend(self.front_task.result()):
                        break
                    self.front_task = asyncio.create_task(self.browser.receive())
                if self.prepare_task is not None and self.prepare_task in done:
                    self.prepare_task.result()
                    self.prepare_task = None
                # Recheck task references: a playback ack can replace the listener.
                if self.speech_task is not None and self.speech_task in done:
                    try:
                        event = json.loads(self.speech_task.result())
                        await self.on_speech(event)
                    except FatalCallError:
                        raise
                    except Exception:
                        await self.error("stt", "speech_disconnected", True)
                        break
                    if self.socket is not None:
                        self.speech_task = asyncio.create_task(self.socket.recv())
                if self.reply_task is not None and self.reply_task in done:
                    self.reply_task.result()
                    self.reply_task = None
        except TimeoutError:
            await self.error("protocol", "start_timeout", True)
        except (FatalCallError, WebSocketDisconnect):
            pass
        finally:
            cleanup = [self.front_task, self.reply_task, self.prepare_task, *self.memory_tasks]
            for task in cleanup:
                if task is not None:
                    task.cancel()
            await asyncio.gather(*(t for t in cleanup if t is not None),
                                 return_exceptions=True)
            with suppress(Exception):
                await self.stop_listening()
            with suppress(Exception):
                await self.set_state("closed")
                await self.browser.close()
