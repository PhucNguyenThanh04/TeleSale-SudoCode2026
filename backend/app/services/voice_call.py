"""One temporary call: transport orchestration, with agent state owned by harness."""

import asyncio
import json
import logging
import re
from collections import deque
from contextlib import suppress
from uuid import UUID, uuid4

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.voice import End, PlaybackFinished, PlaybackProgress, Start, parse_command
from app.services.voice_speech import INPUT_AUDIO, SpeechClient
from app.services.voice_turn import VoiceTurn

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
        self.tts_task = None
        self.active_turn = None
        self.pending_turns = deque()
        self.consumed_inputs = set()
        self.closing = False
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

    async def interrupt(self):
        turn = self.active_turn
        if turn is None or turn.interrupted or turn.playback.is_set():
            return
        turn.interrupted = True
        turn.interruption.set()
        if self.tts_task is not None:
            self.tts_task.cancel()
        await self.send("playback_interrupt", turn_id=turn.turn_id)

    async def synthesize(self, turn: VoiceTurn, text: str):
        index = 0
        segment = 0
        # Speak original sentence units so receipts map to verified source text,
        # even when the speech service expands numbers into Vietnamese words.
        for sentence in re.finditer(r".+?(?:[.!?](?!\d)(?=\s|$)|$)", text, re.DOTALL):
            if not sentence.group().strip():
                continue
            if turn.interrupted:
                return
            async for event in self.speech.stream_tts(sentence.group().strip()):
                if turn.interrupted:
                    return
                if event["event"] == "audio_chunk":
                    await self.send("audio", turn_id=turn.turn_id, index=index,
                                    segment_index=segment,
                                    format={"encoding": "pcm_s16le", "sample_rate": event["sample_rate"],
                                            "channels": 1}, audio_base64=event["pcm16_base64"])
                    index += 1
                elif event["event"] == "segment_end":
                    await self.send("audio_segment_end", turn_id=turn.turn_id,
                                    segment_index=segment, pause_ms=200)
                    segment += 1
            if turn.interrupted:
                return
            turn.marks.add(sentence.end())
            await self.send("audio_mark", turn_id=turn.turn_id, played_chars=sentence.end())
        if not turn.interrupted:
            self.awaiting_playback = True
            await self.send("audio_complete", turn_id=turn.turn_id)

    async def persist_playback(self, turn: VoiceTurn):
        if turn.response is None:
            return
        response = await self.ai_http.post("/v1/chat/turns/playback", json={
            "session_id": self.session_id, "client_msg_id": turn.client_msg_id,
            "channel": self.start.channel, "channel_identity": self.start.channel_identity,
            "on": self.start.on.isoformat(), "played_chars": turn.played_chars,
            "interrupted": turn.interrupted,
        })
        response.raise_for_status()
        result = response.json()
        if result.get("session_id") != self.session_id or result.get("client_msg_id") != turn.client_msg_id:
            raise ValueError("Playback response changed turn")
        update = result["memory_update"]
        if not self.closing:
            await self.send("memory_update", turn_id=turn.turn_id,
                            client_msg_id=turn.client_msg_id, memory_update=update,
                            tracking_finished=update.get("status") != "pending")
            if update.get("status") == "pending":
                task = asyncio.create_task(self.track_memory(turn.turn_id, turn.client_msg_id, update))
                self.memory_tasks.add(task)
                task.add_done_callback(self.memory_tasks.discard)

    async def reply(self, turn: VoiceTurn):
        if self.prepare_task is not None:
            await self.prepare_task
        request = {
            "client_msg_id": turn.client_msg_id, "session_id": self.session_id,
            "channel": self.start.channel, "channel_identity": self.start.channel_identity,
            "on": self.start.on.isoformat(), "text": turn.text,
            "input_mode": "asr_transcript", "delivery_mode": "voice",
        }
        try:
            turn.request_started = True
            response = await self.ai_http.post("/v1/chat/turns", json=request)
            response.raise_for_status()
            result = response.json()
            if str(UUID(result["session_id"])) != self.session_id:
                raise ValueError("Harness changed session")
            agent_text = result["agent_text"]
            if not isinstance(agent_text, str) or not agent_text.strip():
                raise ValueError("Harness returned no answer")
            turn.response = result
        except Exception:
            if not self.closing:
                await self.error("harness", "harness_failed", True, turn_id=turn.turn_id)
            raise FatalCallError from None

        if not turn.interrupted and not self.closing:
            await self.send("agent_reply", turn_id=turn.turn_id, session_id=self.session_id,
                            agent_text=agent_text, call_brief=result.get("call_brief"),
                            needs_handoff=result.get("needs_handoff", False),
                            handoff_ticket_id=result.get("handoff_ticket_id"),
                            memory_update=result.get("memory_update"))
            await self.set_state("speaking")
            self.tts_task = asyncio.create_task(self.synthesize(turn, agent_text))
            try:
                async with asyncio.timeout(120):
                    await self.tts_task
            except asyncio.CancelledError:
                if not turn.interrupted:
                    raise
            except Exception:
                await self.interrupt()
                self.awaiting_playback = True
                await self.error("tts", "tts_failed", False, turn_id=turn.turn_id)
            finally:
                self.tts_task = None
        if self.closing:
            turn.playback.set()
        receipt = asyncio.create_task(turn.playback.wait())
        interruption = asyncio.create_task(turn.interruption.wait())
        try:
            async with asyncio.timeout(120):
                done, _ = await asyncio.wait([receipt, interruption], return_when=asyncio.FIRST_COMPLETED)
                if receipt not in done:
                    async with asyncio.timeout(5):
                        await receipt
        except TimeoutError:
            await self.interrupt()
        finally:
            for task in (receipt, interruption):
                task.cancel()
            await asyncio.gather(receipt, interruption, return_exceptions=True)
        try:
            await self.persist_playback(turn)
        except Exception:
            if not self.closing:
                await self.error("harness", "playback_failed", True, turn_id=turn.turn_id)
            raise FatalCallError from None

    async def start_next(self):
        if self.reply_task is not None or not self.pending_turns:
            return
        turn = self.pending_turns.popleft()
        self.active_turn = turn
        self.turn_id = turn.turn_id
        self.awaiting_playback = False
        await self.set_state("processing")
        self.reply_task = asyncio.create_task(self.reply(turn))

    async def on_speech(self, event: dict):
        name = event["event"]
        if name == "error":
            fatal = event.get("fatal", True)
            code = event.get("code")
            known = {"transcription_failed", "overloaded", "service_unavailable",
                     "invalid_message", "audio_too_large"}
            failed_turn = self.turn_ids.pop(event.get("turn_id"), None)
            if event.get("turn_id"):
                self.consumed_inputs.add(event["turn_id"])
            await self.error("stt", code if code in known else "speech_failed", fatal,
                             turn_id=failed_turn)
            if fatal:
                raise FatalCallError
            return
        if name not in {"speech_started", "speech_ended", "transcript_final"}:
            return
        source_id = event["turn_id"]
        if source_id in self.consumed_inputs:
            return
        turn_id = self.turn_ids.setdefault(source_id, str(uuid4()))
        if name == "speech_started":
            await self.interrupt()
        if name == "transcript_final":
            text = event["text"]
            if not isinstance(text, str):
                raise ValueError("Invalid transcript")
            self.consumed_inputs.add(source_id)
            self.turn_ids.pop(source_id, None)
            if not text.strip():
                return
            await self.interrupt()
            await self.send("transcript_final", turn_id=turn_id, text=text)
            if len(self.pending_turns) >= 4:
                await self.error("stt", "overloaded", True)
                raise FatalCallError
            self.pending_turns.append(VoiceTurn(turn_id, text))
            await self.start_next()
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
            if self.socket is not None:
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
        if isinstance(command, (PlaybackFinished, PlaybackProgress)):
            turn = self.active_turn
            valid = (turn is not None and command.turn_id == turn.turn_id
                     and command.played_chars in turn.marks
                     and command.played_chars >= turn.played_chars)
            if isinstance(command, PlaybackFinished):
                valid = valid and self.awaiting_playback
            elif command.event == "playback_stopped":
                valid = valid and turn.interrupted
            if not valid or turn.playback.is_set():
                await self.error("protocol", "unexpected_playback", False)
                return True
            turn.played_chars = command.played_chars
            if command.event != "playback_progress":
                turn.playback.set()
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
                # The same input stream stays live across generation and playback.
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
                    self.active_turn = None
                    self.turn_id = None
                    self.awaiting_playback = False
                    if self.pending_turns:
                        await self.start_next()
                    else:
                        await self.set_state("listening")
        except TimeoutError:
            await self.error("protocol", "start_timeout", True)
        except (FatalCallError, WebSocketDisconnect):
            pass
        finally:
            self.closing = True
            if self.active_turn is not None:
                self.active_turn.interrupted = True
                self.active_turn.playback.set()
            if self.tts_task is not None:
                self.tts_task.cancel()
            # Let an issued business request finish once; closing a browser is
            # not authorization to roll it back or issue a replacement request.
            if self.reply_task is not None:
                if self.active_turn is not None and not self.active_turn.request_started:
                    self.reply_task.cancel()
                with suppress(Exception, asyncio.CancelledError):
                    await self.reply_task
            cleanup = [self.front_task, self.prepare_task, *self.memory_tasks]
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
