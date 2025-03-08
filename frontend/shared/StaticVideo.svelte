<script lang="ts">
	import { createEventDispatcher, onMount } from "svelte";
	import { BlockLabel, Empty } from "@gradio/atoms";
	import { Video } from "@gradio/icons";

	import { start, stop } from "./webrtc_utils";

	export let value: string | null = null;
	export let label: string | undefined = undefined;
	export let show_label = true;
	export let rtc_configuration: Object | null = null;
	export let on_change_cb: (msg: "change" | "tick") => void;
	export let server: {
		offer: (body: any) => Promise<any>;
	};

	let video_element: HTMLVideoElement;

	let _webrtc_id = Math.random().toString(36).substring(2);

	let pc: RTCPeerConnection;

	const dispatch = createEventDispatcher<{
		error: string;
		tick: undefined;
	}>();

	let stream_state = "closed";

	$: if (value === "start_webrtc_stream") {
		_webrtc_id = Math.random().toString(36).substring(2);
		server
			.turn()
			.then((rtc_configuration_) => {
				rtc_configuration = rtc_configuration_;
			})
			.catch((error) => {
				dispatch("error", error);
			});
		value = _webrtc_id;
		pc = new RTCPeerConnection(rtc_configuration);
		pc.addEventListener("connectionstatechange", async (event) => {
			switch (pc.connectionState) {
				case "connected":
					stream_state = "open";
					dispatch("tick");
					break;
				case "disconnected":
					stop(pc);
					break;
				case "failed":
					stream_state = "closed";
					dispatch("error", "Connection failed!");
					stop(pc);
					break;
				default:
					break;
			}
		});

		const timeoutId = setTimeout(() => {
			// @ts-ignore
			on_change_cb({ type: "connection_timeout" });
		}, 5000);

		start(
			null,
			pc,
			video_element,
			server.offer,
			_webrtc_id,
			"video",
			on_change_cb,
		)
			.then((connection) => {
				clearTimeout(timeoutId);
				pc = connection;
			})
			.catch(() => {
				clearTimeout(timeoutId);
				dispatch(
					"error",
					"Too many concurrent users. Come back later!",
				);
			});
	}
</script>

<BlockLabel {show_label} Icon={Video} label={label || "Video"} />

{#if value === "__webrtc_value__"}
	<Empty unpadded_box={true} size="large"><Video /></Empty>
{/if}
<div class="wrap">
	<video
		class:hidden={value === "__webrtc_value__"}
		bind:this={video_element}
		autoplay={true}
		on:loadeddata={dispatch.bind(null, "loadeddata")}
		on:click={dispatch.bind(null, "click")}
		on:play={dispatch.bind(null, "play")}
		on:pause={dispatch.bind(null, "pause")}
		on:ended={dispatch.bind(null, "ended")}
		on:mouseover={dispatch.bind(null, "mouseover")}
		on:mouseout={dispatch.bind(null, "mouseout")}
		on:focus={dispatch.bind(null, "focus")}
		on:blur={dispatch.bind(null, "blur")}
		on:load
		data-testid={$$props["data-testid"]}
		crossorigin="anonymous"
	>
		<track kind="captions" />
	</video>
</div>

<style>
	.hidden {
		display: none;
	}

	.wrap {
		position: relative;
		background-color: var(--background-fill-secondary);
		height: var(--size-full);
		width: var(--size-full);
		border-radius: var(--radius-xl);
	}
	.wrap :global(video) {
		height: var(--size-full);
		width: var(--size-full);
	}
</style>
