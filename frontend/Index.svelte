<svelte:options accessors={true} />

<script lang="ts">
	import { Block, UploadText } from "@gradio/atoms";
	import Video from "./shared/InteractiveVideo.svelte";
	import { StatusTracker } from "@gradio/statustracker";
	import type { LoadingStatus } from "@gradio/statustracker";
	import StaticVideo from "./shared/StaticVideo.svelte";
	import StaticAudio from "./shared/StaticAudio.svelte";
	import InteractiveAudio from "./shared/InteractiveAudio.svelte";

	export let elem_id = "";
	export let elem_classes: string[] = [];
	export let visible = true;
	export let value: string = "__webrtc_value__";
	export let button_labels: { start: string; stop: string; waiting: string };

	export let label: string;
	export let root: string;
	export let show_label: boolean;
	export let loading_status: LoadingStatus;
	export let height: number | undefined;
	export let width: number | undefined;
	export let server: {
		offer: (body: any) => Promise<any>;
		turn: () => Promise<any>;
	};

	export let container = false;
	export let scale: number | null = null;
	export let min_width: number | undefined = undefined;
	export let gradio;
	export let rtc_configuration: Object;
	export let time_limit: number | null = null;
	export let modality: "video" | "audio" | "audio-video" = "video";
	export let mode: "send-receive" | "receive" | "send" = "send-receive";
	export let rtp_params: RTCRtpParameters = {} as RTCRtpParameters;
	export let track_constraints: MediaTrackConstraints = {};
	export let icon: string | undefined = undefined;
	export let icon_button_color: string = "var(--color-accent)";
	export let pulse_color: string = "var(--color-accent)";
	export let icon_radius: number = 50;

	const on_change_cb = (msg: "change" | "tick" | any) => {
		if (
			msg?.type === "info" ||
			msg?.type === "warning" ||
			msg?.type === "error"
		) {
			gradio.dispatch(
				msg?.type === "error" ? "error" : "warning",
				msg.message,
			);
		} else if (msg?.type === "fetch_output") {
			gradio.dispatch("state_change");
		} else if (msg?.type === "send_input") {
			gradio.dispatch("tick");
		} else if (msg?.type === "connection_timeout") {
			gradio.dispatch(
				"warning",
				"Taking a while to connect. Are you on a VPN?",
			);
		}
		if (msg.type === "state_change") {
			gradio.dispatch(msg === "change" ? "state_change" : "tick");
		}
	};

	const reject_cb = (msg: object) => {
		if (
			msg.status === "failed" &&
			msg.meta?.error === "concurrency_limit_reached"
		) {
			gradio.dispatch(
				"error",
				`Too many concurrent connections. Please try again later!`,
			);
		} else {
			gradio.dispatch("error", "Unexpected server error");
		}
	};

	let dragging = false;
</script>

<Block
	{visible}
	variant={"solid"}
	border_mode={dragging ? "focus" : "base"}
	padding={false}
	{elem_id}
	{elem_classes}
	{height}
	{width}
	{container}
	{scale}
	{min_width}
	allow_overflow={false}
>
	<StatusTracker
		autoscroll={gradio.autoscroll}
		i18n={gradio.i18n}
		{...loading_status}
		on:clear_status={() => gradio.dispatch("clear_status", loading_status)}
	/>

	{#if mode == "receive" && modality === "video"}
		<StaticVideo
			bind:value
			{on_change_cb}
			{label}
			{show_label}
			{server}
			{rtc_configuration}
			on:tick={() => gradio.dispatch("tick")}
			on:error={({ detail }) => gradio.dispatch("error", detail)}
		/>
	{:else if mode == "receive" && modality === "audio"}
		<StaticAudio
			bind:value
			{on_change_cb}
			{label}
			{show_label}
			{server}
			{rtc_configuration}
			{icon}
			{icon_button_color}
			{pulse_color}
			{icon_radius}
			i18n={gradio.i18n}
			on:tick={() => gradio.dispatch("tick")}
			on:error={({ detail }) => gradio.dispatch("error", detail)}
		/>
	{:else if (mode === "send-receive" || mode == "send") && (modality === "video" || modality == "audio-video")}
		<Video
			bind:value
			{label}
			{show_label}
			active_source={"webcam"}
			include_audio={modality === "audio-video"}
			{server}
			{rtc_configuration}
			{time_limit}
			{mode}
			{track_constraints}
			{rtp_params}
			{on_change_cb}
			{reject_cb}
			{icon}
			{icon_button_color}
			{pulse_color}
			{icon_radius}
			{button_labels}
			on:clear={() => gradio.dispatch("clear")}
			on:play={() => gradio.dispatch("play")}
			on:pause={() => gradio.dispatch("pause")}
			on:upload={() => gradio.dispatch("upload")}
			on:stop={() => gradio.dispatch("stop")}
			on:end={() => gradio.dispatch("end")}
			on:start_recording={() => gradio.dispatch("start_recording")}
			on:stop_recording={() => gradio.dispatch("stop_recording")}
			on:tick={() => gradio.dispatch("tick")}
			on:error={({ detail }) => gradio.dispatch("error", detail)}
			i18n={gradio.i18n}
			stream_handler={(...args) => gradio.client.stream(...args)}
		>
			<UploadText i18n={gradio.i18n} type="video" />
		</Video>
	{:else if (mode === "send-receive" || mode === "send") && modality === "audio"}
		<InteractiveAudio
			bind:value
			{on_change_cb}
			{label}
			{show_label}
			{server}
			{rtc_configuration}
			{time_limit}
			{track_constraints}
			{mode}
			{rtp_params}
			i18n={gradio.i18n}
			{icon}
			{reject_cb}
			{icon_button_color}
			{icon_radius}
			{pulse_color}
			{button_labels}
			on:tick={() => gradio.dispatch("tick")}
			on:error={({ detail }) => gradio.dispatch("error", detail)}
			on:warning={({ detail }) => gradio.dispatch("warning", detail)}
		/>
	{/if}
</Block>
