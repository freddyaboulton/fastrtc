<script lang="ts">
    import { BlockLabel } from "@gradio/atoms";
    import type { I18nFormatter } from "@gradio/utils";
    import { createEventDispatcher } from "svelte";
    import { onMount } from "svelte";
    import { fade } from "svelte/transition";
    import { StreamingBar } from "@gradio/statustracker";
    import {
        Circle,
        Spinner,
        Music,
        DropdownArrow,
        VolumeMuted,
        VolumeHigh,
        Microphone,
    } from "@gradio/icons";

    import { start, stop } from "./webrtc_utils";
    import { get_devices, set_available_devices } from "./stream_utils";
    import AudioWave from "./AudioWave.svelte";
    import WebcamPermissions from "./WebcamPermissions.svelte";
    import PulsingIcon from "./PulsingIcon.svelte";
    export let mode: "send-receive" | "send";
    export let value: string | null = null;
    export let label: string | undefined = undefined;
    export let show_label = true;
    export let rtc_configuration: Object | null = null;
    export let i18n: I18nFormatter;
    export let time_limit: number | null = null;
    export let track_constraints: MediaTrackConstraints = {};
    export let rtp_params: RTCRtpParameters = {} as RTCRtpParameters;
    export let on_change_cb: (mg: "tick" | "change") => void;
    export let reject_cb: (msg: object) => void;
    export let icon: string | undefined = undefined;
    export let icon_button_color: string = "var(--color-accent)";
    export let pulse_color: string = "var(--color-accent)";
    export let icon_radius: number = 50;
    export let button_labels: { start: string; stop: string; waiting: string };
    let pending = false;

    let stopword_recognized = false;

    let notification_sound;

    onMount(() => {
        if (value === "__webrtc_value__") {
            notification_sound = new Audio(
                "https://huggingface.co/datasets/freddyaboulton/bucket/resolve/main/pop-sounds.mp3",
            );
        }
    });

    let _on_change_cb = (msg: "change" | "tick" | "stopword") => {
        if (msg === "stopword") {
            stopword_recognized = true;
            setTimeout(() => {
                stopword_recognized = false;
            }, 3000);
        } else {
            console.debug("calling on_change_cb with msg", msg);
            on_change_cb(msg);
        }
    };

    let options_open = false;

    let _time_limit: number | null = null;

    export let server: {
        offer: (body: any) => Promise<any>;
        turn: () => Promise<any>;
    };

    let stream_state: "open" | "closed" | "waiting" = "closed";
    let audio_player: HTMLAudioElement;
    let pc: RTCPeerConnection;
    let _webrtc_id = null;
    let stream: MediaStream;
    let available_audio_devices: MediaDeviceInfo[];
    let selected_device: MediaDeviceInfo | null = null;
    let mic_accessed = false;
    let is_muted = false;

    const audio_source_callback = () => {
        if (mode === "send") return stream;
        else return audio_player.srcObject as MediaStream;
    };

    const dispatch = createEventDispatcher<{
        tick: undefined;
        state_change: undefined;
        error: string;
        play: undefined;
        stop: undefined;
    }>();

    async function access_mic(): Promise<void> {
        try {
            const constraints = selected_device
                ? {
                      deviceId: { exact: selected_device.deviceId },
                      ...track_constraints,
                  }
                : track_constraints;
            const stream_ = await navigator.mediaDevices.getUserMedia({
                audio: constraints,
            });
            stream = stream_;
        } catch (err) {
            if (!navigator.mediaDevices) {
                dispatch("error", i18n("audio.no_device_support"));
                return;
            }
            if (err instanceof DOMException && err.name == "NotAllowedError") {
                dispatch("error", i18n("audio.allow_recording_access"));
                return;
            }
            throw err;
        }
        available_audio_devices = set_available_devices(
            await get_devices(),
            "audioinput",
        );
        mic_accessed = true;
        const used_devices = stream
            .getTracks()
            .map((track) => track.getSettings()?.deviceId)[0];

        selected_device = used_devices
            ? available_audio_devices.find(
                  (device) => device.deviceId === used_devices,
              ) || available_audio_devices[0]
            : available_audio_devices[0];
    }

    async function start_stream(): Promise<void> {
        if (stream_state === "open") {
            stop(pc);
            stream_state = "closed";
            _time_limit = null;
            await access_mic();
            return;
        }
        _webrtc_id = Math.random().toString(36).substring(2);
        value = _webrtc_id;
        stream_state = "waiting";
        await server.turn().then((rtc_configuration_) => {
            if (rtc_configuration_.error) {
                dispatch("error", rtc_configuration_.error);
                return;
            }
            rtc_configuration = rtc_configuration_;
            console.info("rtc_configuration", rtc_configuration_);
        });
        pc = new RTCPeerConnection(rtc_configuration);
        console.info("created");
        pc.addEventListener("connectionstatechange", async (event) => {
            switch (pc.connectionState) {
                case "connected":
                    console.info("connected");
                    stream_state = "open";
                    _time_limit = time_limit;
                    break;
                case "disconnected":
                    console.info("closed");
                    stream_state = "closed";
                    _time_limit = null;
                    stop(pc);
                    break;
                case "failed":
                    console.info("failed");
                    stream_state = "closed";
                    _time_limit = null;
                    dispatch("error", "Connection failed!");
                    stop(pc);
                    break;
                default:
                    break;
            }
        });
        stream = null;

        try {
            await access_mic();
        } catch (err) {
            if (!navigator.mediaDevices) {
                dispatch("error", i18n("audio.no_device_support"));
                return;
            }
            if (err instanceof DOMException && err.name == "NotAllowedError") {
                dispatch("error", i18n("audio.allow_recording_access"));
                return;
            }
            throw err;
        }
        if (stream == null) return;

        const additional_message_cb = (msg: object) => {
            // @ts-ignore
            if (msg.type === "log" && msg.data === "pause_detected") {
                pending = true;
                // @ts-ignore
            } else if (msg.type === "log" && msg.data === "response_starting") {
                pending = false;
            }
        };

        const timeoutId = setTimeout(() => {
            // @ts-ignore
            _on_change_cb({ type: "connection_timeout" });
        }, 5000);

        start(
            stream,
            pc,
            mode === "send" ? null : audio_player,
            server.offer,
            _webrtc_id,
            "audio",
            _on_change_cb,
            rtp_params,
            additional_message_cb,
            reject_cb,
        )
            .then((connection) => {
                clearTimeout(timeoutId);
                pc = connection;
            })
            .catch(() => {
                console.info("catching");
                clearTimeout(timeoutId);
                stream_state = "closed";
            });
    }

    function handle_click_outside(event: MouseEvent): void {
        event.preventDefault();
        event.stopPropagation();
        options_open = false;
    }

    function click_outside(node: Node, cb: any): any {
        const handle_click = (event: MouseEvent): void => {
            if (
                node &&
                !node.contains(event.target as Node) &&
                !event.defaultPrevented
            ) {
                cb(event);
            }
        };

        document.addEventListener("click", handle_click, true);

        return {
            destroy() {
                document.removeEventListener("click", handle_click, true);
            },
        };
    }

    const handle_device_change = async (event: InputEvent): Promise<void> => {
        const target = event.target as HTMLInputElement;
        const device_id = target.value;

        stream = await navigator.mediaDevices.getUserMedia({
            audio: { deviceId: { exact: device_id }, ...track_constraints },
        });
        selected_device =
            available_audio_devices.find(
                (device) => device.deviceId === device_id,
            ) || null;
        options_open = false;
    };

    function toggleMute(): void {
        if (audio_player) {
            audio_player.muted = !audio_player.muted;
            is_muted = audio_player.muted;
        }
    }

    $: if (stopword_recognized) {
        notification_sound.play();
    }
</script>

<BlockLabel
    {show_label}
    Icon={Music}
    float={false}
    label={label || i18n("audio.audio")}
/>
<div class="audio-container">
    <audio
        class="standard-player"
        class:hidden={value === "__webrtc_value__"}
        on:load
        bind:this={audio_player}
        on:ended={() => dispatch("stop")}
        on:play={() => dispatch("play")}
    />
    {#if !mic_accessed}
        <div
            in:fade={{ delay: 100, duration: 200 }}
            title="grant webcam access"
            style="height: 100%"
        >
            <WebcamPermissions
                icon={Microphone}
                on:click={async () => access_mic()}
            />
        </div>
    {:else}
        <AudioWave
            {audio_source_callback}
            {stream_state}
            {icon}
            {icon_button_color}
            {pulse_color}
            {pending}
            {icon_radius}
        />
        <StreamingBar time_limit={_time_limit} />
        <div class="button-wrap" class:pulse={stopword_recognized}>
            <button on:click={start_stream} aria-label={"start stream"}>
                {#if stream_state === "waiting"}
                    <div class="icon-with-text">
                        <div class="icon color-primary" title="spinner">
                            <Spinner />
                        </div>
                        {button_labels.waiting || "Connecting..."}
                    </div>
                {:else if stream_state === "open"}
                    <div class="icon-with-text">
                        {#if mode === "send-receive"}
                            <div
                                class="icon"
                                title="stop recording"
                                style={`fill: ${icon_button_color}; stroke: ${icon_button_color}; color: ${icon_button_color};`}
                            >
                                <PulsingIcon
                                    audio_source_callback={() => stream}
                                    stream_state={"open"}
                                    icon={Circle}
                                    {icon_button_color}
                                    {pulse_color}
                                />
                            </div>
                        {:else}
                            <div
                                class="icon color-primary"
                                title="start recording"
                            >
                                <Circle />
                            </div>
                        {/if}
                        {button_labels.stop || i18n("audio.stop")}
                    </div>
                {:else}
                    <div class="icon-with-text">
                        <div class="icon color-primary" title="start recording">
                            <Circle />
                        </div>
                        {button_labels.start || i18n("audio.record")}
                    </div>
                {/if}
            </button>
            {#if stream_state === "closed"}
                <button
                    class="icon"
                    on:click={() => (options_open = true)}
                    aria-label="select input source"
                >
                    <DropdownArrow />
                </button>
            {/if}
            {#if stream_state === "open" && mode === "send-receive"}
                <button
                    class="mute-button"
                    on:click={toggleMute}
                    aria-label={is_muted ? "unmute audio" : "mute audio"}
                >
                    <div
                        class="icon"
                        style={`fill: ${icon_button_color}; stroke: ${icon_button_color}; color: ${icon_button_color};`}
                    >
                        {#if is_muted}
                            <VolumeMuted />
                        {:else}
                            <VolumeHigh />
                        {/if}
                    </div>
                </button>
            {/if}
            {#if options_open && selected_device}
                <select
                    class="select-wrap"
                    aria-label="select source"
                    use:click_outside={handle_click_outside}
                    on:change={handle_device_change}
                >
                    <button
                        class="inset-icon"
                        on:click|stopPropagation={() => (options_open = false)}
                    >
                        <DropdownArrow />
                    </button>
                    {#if available_audio_devices.length === 0}
                        <option value="">{i18n("common.no_devices")}</option>
                    {:else}
                        {#each available_audio_devices as device}
                            <option
                                value={device.deviceId}
                                selected={selected_device.deviceId ===
                                    device.deviceId}
                            >
                                {device.label}
                            </option>
                        {/each}
                    {/if}
                </select>
            {/if}
        </div>
    {/if}
</div>

<style>
    .audio-container {
        display: flex;
        height: 100%;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }

    :global(::part(wrapper)) {
        margin-bottom: var(--size-2);
    }

    .standard-player {
        width: 100%;
        padding: var(--size-2);
    }

    .hidden {
        display: none;
    }

    .button-wrap {
        margin-top: var(--size-2);
        margin-bottom: var(--size-2);
        background-color: var(--block-background-fill);
        border: 1px solid var(--border-color-primary);
        border-radius: var(--radius-xl);
        padding: var(--size-1-5);
        display: flex;
        bottom: var(--size-2);
        box-shadow: var(--shadow-drop-lg);
        border-radius: var(--radius-xl);
        line-height: var(--size-3);
        color: var(--button-secondary-text-color);
    }

    @keyframes pulse {
        0% {
            transform: scale(1);
            box-shadow: 0 0 0 0 rgba(var(--primary-500-rgb), 0.7);
        }

        70% {
            transform: scale(1.25);
            box-shadow: 0 0 0 10px rgba(var(--primary-500-rgb), 0);
        }

        100% {
            transform: scale(1);
            box-shadow: 0 0 0 0 rgba(var(--primary-500-rgb), 0);
        }
    }

    .pulse {
        animation: pulse 1s infinite;
    }

    .icon-with-text {
        min-width: var(--size-16);
        align-items: center;
        margin: 0 var(--spacing-xl);
        display: flex;
        justify-content: space-evenly;
        gap: var(--size-2);
    }

    @media (--screen-md) {
        button {
            bottom: var(--size-4);
        }
    }

    @media (--screen-xl) {
        button {
            bottom: var(--size-8);
        }
    }

    .icon {
        width: 18px;
        height: 18px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .color-primary {
        fill: var(--primary-600);
        stroke: var(--primary-600);
        color: var(--primary-600);
    }

    .select-wrap {
        -webkit-appearance: none;
        -moz-appearance: none;
        appearance: none;
        color: var(--button-secondary-text-color);
        background-color: transparent;
        width: 95%;
        font-size: var(--text-md);
        position: absolute;
        bottom: var(--size-2);
        background-color: var(--block-background-fill);
        box-shadow: var(--shadow-drop-lg);
        border-radius: var(--radius-xl);
        z-index: var(--layer-top);
        border: 1px solid var(--border-color-primary);
        text-align: left;
        line-height: var(--size-4);
        white-space: nowrap;
        text-overflow: ellipsis;
        left: 50%;
        transform: translate(-50%, 0);
        max-width: var(--size-52);
    }

    .select-wrap > option {
        padding: 0.25rem 0.5rem;
        border-bottom: 1px solid var(--border-color-accent);
        padding-right: var(--size-8);
        text-overflow: ellipsis;
        overflow: hidden;
    }

    .select-wrap > option:hover {
        background-color: var(--color-accent);
    }

    .select-wrap > option:last-child {
        border: none;
    }

    .mute-button {
        background-color: var(--block-background-fill);
        padding-right: var(--size-2);
        display: flex;
        color: var(--button-secondary-text-color);
    }
</style>
