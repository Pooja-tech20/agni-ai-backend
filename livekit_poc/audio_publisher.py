"""
Agni AI - LiveKit Microphone Audio Publisher

Captures real microphone audio and publishes it to a LiveKit room.

This file is a local development/test client.

For the production Exotel integration, the caller's phone handles
its own microphone, speaker, headset, and Bluetooth routing.

Local test flow:

    Laptop Microphone
        ↓
    MediaDevices Input
    AEC enabled
        ↓
    LocalAudioTrack
        ↓
    LiveKit Room
        ↓
    Agni AI
        ↓
    voice-output
        ↓
    MediaDevices Output
        ↓
    Laptop Speaker

Using the same MediaDevices instance for input and output allows
LiveKit's WebRTC audio processing module to use speaker playback
as the AEC reverse/reference stream.
"""

import asyncio
import json
import logging
import os
import urllib.request

from dotenv import load_dotenv
from livekit import rtc

from livekit_poc.realtime_media_devices import RealtimeMediaDevices


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

load_dotenv(
    ".env.local",
    override=True,
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class _AudioMixerTimeoutFilter(logging.Filter):
    """
    Hide the expected LiveKit AudioMixer warning that occurs
    while the remote voice-output track is temporarily silent.
    """

    def filter(
        self,
        record: logging.LogRecord,
    ) -> bool:
        message = record.getMessage()

        return not (
            message.startswith(
                "AudioMixer: stream "
            )
            and message.endswith(
                " timeout, ignoring"
            )
        )


logging.getLogger(
    "livekit"
).addFilter(
    _AudioMixerTimeoutFilter()
)


# ---------------------------------------------------------------------------
# Room / participant configuration
# ---------------------------------------------------------------------------

AGENT_API_URL = os.getenv(
    "AGNI_AGENT_API_URL",
    "http://127.0.0.1:8001",
)


def create_agent_session() -> tuple[str, str]:
    agent_id = os.getenv("AGNI_TEST_AGENT_ID", "").strip()
    access_token = os.getenv("AGNI_TEST_ACCESS_TOKEN", "").strip()

    if not agent_id or not access_token:
        raise RuntimeError(
            "Set AGNI_TEST_AGENT_ID and AGNI_TEST_ACCESS_TOKEN "
            "before running the publisher."
        )

    payload = json.dumps({
        "agent_id": agent_id
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{AGENT_API_URL}/api/v1/sessions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=10,
    ) as response:
        data = json.loads(
            response.read().decode("utf-8")
        )

    return (
        data["livekit"]["room_name"],
        data["livekit"]["token"],
    )


# ---------------------------------------------------------------------------
# Local laptop device selection
# ---------------------------------------------------------------------------

def select_laptop_microphone(
    media_devices: rtc.MediaDevices,
) -> int:
    """
    Select the laptop's built-in microphone array.

    Bluetooth/headset microphones are intentionally ignored because
    this module is only used as the local Agni development harness.
    """

    input_devices = media_devices.list_input_devices()

    # Prefer the built-in Intel microphone array.
    for device in input_devices:
        name = str(
            device.get(
                "name",
                "",
            )
        ).lower()

        if (
            "microphone array" in name
            and "intel" in name
        ):
            print(
                "Laptop microphone selected:"
            )

            print(
                f"  Input:  "
                f"[{device['index']}] "
                f"{device['name']}"
            )

            return int(
                device["index"]
            )

    # Some audio backends expose the same microphone without
    # including "Intel" in the name.
    for device in input_devices:
        name = str(
            device.get(
                "name",
                "",
            )
        ).lower()

        if "microphone" in name:
            print(
                "Laptop microphone selected:"
            )

            print(
                f"  Input:  "
                f"[{device['index']}] "
                f"{device['name']}"
            )

            return int(
                device["index"]
            )

    raise RuntimeError(
        "Laptop microphone array could not be found."
    )


def select_laptop_speaker(
    media_devices: rtc.MediaDevices,
) -> int:
    """
    Select the laptop's built-in Realtek speaker output.

    Bluetooth/headphone outputs are intentionally ignored because
    this module is only used as the local Agni development harness.
    """

    output_devices = media_devices.list_output_devices()

    # Prefer the normal Realtek laptop speaker endpoint.
    for device in output_devices:
        name = str(
            device.get(
                "name",
                "",
            )
        ).lower()

        if (
            "speakers" in name
            and "realtek" in name
        ):
            print(
                "Laptop speaker selected:"
            )

            print(
                f"  Output: "
                f"[{device['index']}] "
                f"{device['name']}"
            )

            return int(
                device["index"]
            )

    # Fallback for systems where the Realtek name differs slightly.
    for device in output_devices:
        name = str(
            device.get(
                "name",
                "",
            )
        ).lower()

        if (
            "speaker" in name
            and "headphone" not in name
            and "headset" not in name
        ):
            print(
                "Laptop speaker selected:"
            )

            print(
                f"  Output: "
                f"[{device['index']}] "
                f"{device['name']}"
            )

            return int(
                device["index"]
            )

    raise RuntimeError(
        "Laptop speaker output could not be found."
    )


# ---------------------------------------------------------------------------
# Main microphone publishing flow
# ---------------------------------------------------------------------------

async def main() -> None:
    """
    Connect to LiveKit, publish laptop microphone audio,
    and play Agni's voice through the laptop speaker.
    """

    livekit_url = os.getenv(
        "LIVEKIT_URL"
    )

    if not livekit_url:
        raise RuntimeError(
            "LIVEKIT_URL is missing from .env.local"
        )

    room = rtc.Room()

    # -----------------------------------------------------------------------
    # Initialize MediaDevices
    # -----------------------------------------------------------------------
    #
    # The same MediaDevices instance handles both microphone capture
    # and Agni playback.
    #
    # This allows the WebRTC audio-processing module to receive
    # speaker playback as the AEC reverse/reference stream.
    #
    # Local laptop speaker/microphone configuration.
    #
    # AEC is enabled to reduce speaker echo reaching
    # the microphone during full-duplex testing.
    #
    # Noise suppression and automatic gain control
    # remain disabled for the current local test setup.

    # LiveKit APM processes 10ms frames; avoid the SDK default 100ms I/O batches.
    media_devices = RealtimeMediaDevices(blocksize=480)

    input_device = select_laptop_microphone(
        media_devices
    )

    output_device = select_laptop_speaker(
        media_devices
    )

    # -----------------------------------------------------------------------
    # Create agent session before opening microphone
    # -----------------------------------------------------------------------

    print("Creating Agni AI session...")

    session_room_name, session_token = (
        create_agent_session()
    )

    print(
        f"Session created: {session_room_name}"
    )

    # -----------------------------------------------------------------------
    # Laptop microphone input
    # -----------------------------------------------------------------------

    input_capture = media_devices.open_input(
        enable_aec=True,
        noise_suppression=False,
        high_pass_filter=True,
        auto_gain_control=False,
        input_device=input_device,
    )

    # -----------------------------------------------------------------------
    # Laptop speaker output
    # -----------------------------------------------------------------------

    # A buffer clear alone is ineffective: the SDK AudioMixer can refill the
    # OutputPlayer after the clear. Closing the player closes its mixer and
    # AudioStream as well, then the next AI turn can attach a fresh stream.
    output_player = None
    voice_track: rtc.Track | None = None
    playback_lock = asyncio.Lock()
    control_tasks: set[asyncio.Task[None]] = set()
    playback_task = None

    async def set_voice_playback(enabled: bool) -> None:
        nonlocal output_player
        async with playback_lock:
            if not enabled:
                if output_player is not None:
                    player = output_player
                    output_player = None
                    await player.aclose()
                    print("[BARGE-IN] Laptop speaker playback stopped.")
                return

            if output_player is not None or voice_track is None:
                return

            player = media_devices.open_output(output_device=output_device)
            try:
                await player.add_track(voice_track)
                await player.start()
            except BaseException:
                await player.aclose()
                raise
            output_player = player
            print("\nAgni voice playback started through laptop speaker")

    @room.on("data_received")
    def on_data_received(packet: rtc.DataPacket) -> None:
        if packet.topic != "agni/audio-control":
            return
        if packet.data not in (b"stop", b"resume"):
            return
        task = asyncio.create_task(set_voice_playback(packet.data == b"resume"))
        control_tasks.add(task)

        def finish_control(completed: asyncio.Task[None]) -> None:
            control_tasks.discard(completed)
            if not completed.cancelled():
                error = completed.exception()
                if error is not None:
                    print(f"Audio playback control failed: {error}")

        task.add_done_callback(finish_control)

    # -----------------------------------------------------------------------
    # Play Agni voice
    # -----------------------------------------------------------------------

    async def play_voice_output(track: rtc.Track) -> None:
        nonlocal voice_track
        voice_track = track
        await set_voice_playback(True)

    # -----------------------------------------------------------------------
    # LiveKit remote track subscription
    # -----------------------------------------------------------------------

    @room.on(
        "track_subscribed"
    )
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        nonlocal playback_task

        if (
            track.kind
            != rtc.TrackKind.KIND_AUDIO
        ):
            return

        if (
            publication.name
            != "voice-output"
        ):
            return

        print(
            "\nSubscribed to Agni voice track "
            f"'{publication.name}' "
            f"from '{participant.identity}'"
        )

        if (
            playback_task is None
            or playback_task.done()
        ):
            playback_task = asyncio.create_task(
                play_voice_output(
                    track
                )
            )

    # -----------------------------------------------------------------------
    # Connect to LiveKit
    # -----------------------------------------------------------------------

    print(
        "Connecting to LiveKit..."
    )

    await room.connect(
        livekit_url,
        session_token,
    )

    print(
        "Connected to LiveKit"
    )

    print(
        f"Room: {room.name}"
    )

    print(
        "Participant: "
        f"{room.local_participant.identity}"
    )

    # -----------------------------------------------------------------------
    # Create microphone track
    # -----------------------------------------------------------------------

    microphone_track = (
        rtc.LocalAudioTrack.create_audio_track(
            "microphone",
            input_capture.source,
        )
    )

    # -----------------------------------------------------------------------
    # Publish microphone audio
    # -----------------------------------------------------------------------

    publication = (
        await room.local_participant.publish_track(
            microphone_track
        )
    )

    print(
        "\nMicrophone audio published"
    )

    print(
        f"Track: {publication.name}"
    )

    print(
        "Audio processing: "
        "AEC enabled, "
        "NS disabled, "
        "AGC disabled"
    )

    print(
        "\nSpeak into the laptop microphone..."
    )

    print(
        "Press Ctrl+C to stop."
    )

    try:
        while True:
            await asyncio.sleep(
                1
            )

    except KeyboardInterrupt:
        print(
            "\nStopping microphone publisher..."
        )

    finally:
        # -------------------------------------------------------------------
        # Stop playback task
        # -------------------------------------------------------------------

        if (
            playback_task is not None
            and not playback_task.done()
        ):
            playback_task.cancel()

            await asyncio.gather(
                playback_task,
                return_exceptions=True,
            )

        # -------------------------------------------------------------------
        # Stop receiver and release speaker/mixer, including control tasks
        # -------------------------------------------------------------------

        for task in tuple(control_tasks):
            task.cancel()
        if control_tasks:
            await asyncio.gather(*control_tasks, return_exceptions=True)
        await set_voice_playback(False)

        # -------------------------------------------------------------------
        # Close microphone capture
        # -------------------------------------------------------------------

        await input_capture.aclose()

        # -------------------------------------------------------------------
        # Disconnect from LiveKit
        # -------------------------------------------------------------------

        await room.disconnect()

        print(
            "Disconnected from LiveKit"
        )


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        asyncio.run(
            main()
        )

    except KeyboardInterrupt:
        print(
            "\nApplication stopped by user."
        )