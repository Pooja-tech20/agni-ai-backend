"""Local LiveKit test microphone capture with a safe, bounded frame queue.

This preserves the existing LiveKit MediaDevices AEC setup. The SDK version
bundled with this project schedules ``q.put_nowait`` from an audio callback
*after* checking ``q.full``; a burst can fill the queue before that scheduled
callback runs, producing an uncaught asyncio.QueueFull exception.

This override changes only the enqueue step: capacity is checked and applied
on the event-loop thread, and stale frames are discarded if capture falls
behind. This is a local test-client fix, not a production telephony API.
"""

from __future__ import annotations

import asyncio
from typing import Any

from livekit import rtc
from livekit.rtc.media_devices import InputCapture, _APMDelayEstimator


FRAME_SAMPLES = 480  # 10 ms at the 48 kHz device sample rate


def put_latest_frame(queue: asyncio.Queue, frame: rtc.AudioFrame) -> bool:
    """Enqueue without QueueFull, preferring current speech over stale audio.

    Called only on the owning asyncio event loop.
    Returns True when an older frame was discarded.
    """
    dropped = False
    if queue.full():
        queue.get_nowait()
        dropped = True
    queue.put_nowait(frame)
    return dropped


class RealtimeMediaDevices(rtc.MediaDevices):
    """Local mic device with the original SDK AEC and a safe audio queue."""

    def open_input(
        self,
        *,
        enable_aec: bool = True,
        noise_suppression: bool = True,
        high_pass_filter: bool = True,
        auto_gain_control: bool = True,
        input_device: int | None = None,
        queue_capacity: int = 50,
        input_channel_index: int | None = None,
    ) -> InputCapture:
        import sounddevice as sd

        loop = self._loop
        source = rtc.AudioSource(self._in_sr, self._channels, loop=loop)
        apm = None
        if enable_aec or noise_suppression or high_pass_filter or auto_gain_control:
            apm = rtc.AudioProcessingModule(
                echo_cancellation=enable_aec,
                noise_suppression=noise_suppression,
                high_pass_filter=high_pass_filter,
                auto_gain_control=auto_gain_control,
            )

        estimator = _APMDelayEstimator() if apm is not None else None
        self._apm = apm
        self._delay_estimator = estimator

        queue: asyncio.Queue[rtc.AudioFrame] = asyncio.Queue(maxsize=queue_capacity)
        dropped_frames = 0

        def _enqueue_on_loop(frame: rtc.AudioFrame) -> None:
            nonlocal dropped_frames
            if put_latest_frame(queue, frame):
                dropped_frames += 1
                if dropped_frames == 1 or dropped_frames % 100 == 0:
                    print(f"[MIC] Capture backlog: {dropped_frames} stale 10ms frame(s) dropped")

        def _callback(indata: Any, frame_count: int, time_info: Any, status: Any) -> None:
            if apm is not None:
                try:
                    input_delay = float(time_info.currentTime - time_info.inputBufferAdcTime)
                    output_delay = float(estimator.get_output_delay()) if estimator else 0.0
                    apm.set_stream_delay_ms(int(max((input_delay + output_delay) * 1000, 0)))
                except Exception:
                    pass

            for i in range(frame_count // FRAME_SAMPLES):
                chunk = indata[i * FRAME_SAMPLES : (i + 1) * FRAME_SAMPLES, 0]
                frame = rtc.AudioFrame(
                    data=chunk.tobytes(),
                    samples_per_channel=FRAME_SAMPLES,
                    sample_rate=self._in_sr,
                    num_channels=self._channels,
                )
                if apm is not None:
                    try:
                        apm.process_stream(frame)
                    except Exception:
                        pass
                try:
                    loop.call_soon_threadsafe(_enqueue_on_loop, frame)
                except RuntimeError:
                    # The event loop is shutting down.
                    return

        input_stream = sd.InputStream(
            callback=_callback,
            dtype="int16",
            channels=self._channels,
            device=input_device,
            samplerate=self._in_sr,
            blocksize=self._blocksize,
        )
        input_stream.start()

        async def _pump() -> None:
            while True:
                try:
                    frame = await queue.get()
                except asyncio.CancelledError:
                    break
                try:
                    await source.capture_frame(frame)
                except Exception:
                    # Preserve the original SDK capture-pump behavior.
                    pass

        task = asyncio.create_task(_pump())
        return InputCapture(
            source=source,
            input_stream=input_stream,
            task=task,
            apm=apm,
            delay_estimator=estimator,
        )
