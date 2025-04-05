export function get_devices(): Promise<MediaDeviceInfo[]> {
  return navigator.mediaDevices.enumerateDevices();
}

export function handle_error(error: string): void {
  throw new Error(error);
}

export function set_local_stream(
  local_stream: MediaStream | null,
  video_source: HTMLVideoElement
): void {
  video_source.srcObject = local_stream;
  video_source.muted = true;
  video_source.play();
}

export async function get_video_stream(
  include_audio: boolean | { deviceId: { exact: string } },
  video_source: HTMLVideoElement,
  device_id?: string,
  track_constraints?:
    | MediaTrackConstraints
    | { video: MediaTrackConstraints; audio: MediaTrackConstraints }
): Promise<MediaStream> {
  const video_fallback_constraints = (track_constraints as any)?.video ||
    track_constraints || {
      width: { ideal: 500 },
      height: { ideal: 500 },
    };
  const audio_fallback_constraints = (track_constraints as any)?.audio ||
    track_constraints;

  const constraints = {
    video: device_id
      ? { deviceId: { exact: device_id }, ...video_fallback_constraints }
      : video_fallback_constraints,
    audio: include_audio
      ? typeof include_audio === "object"
        ? { ...include_audio, ...audio_fallback_constraints }
        : audio_fallback_constraints
      : false,
  };
  return navigator.mediaDevices
    .getUserMedia(constraints)
    .then((local_stream: MediaStream) => {
      set_local_stream(local_stream, video_source);
      return local_stream;
    });
}

export function set_available_devices(
  devices: MediaDeviceInfo[],
  kind: "videoinput" | "audioinput" = "videoinput"
): MediaDeviceInfo[] {
  const cameras = devices.filter(
    (device: MediaDeviceInfo) => device.kind === kind
  );

  return cameras;
}
