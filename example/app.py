from multiprocessing import freeze_support
from fastrtc_canary import get_stt_model, load_audio

def main():
    # Load model
    model = get_stt_model(
        model="nvidia/canary-1b",
        lang="en",
    )

    # Load audio file (automatically resamples to 16kHz)
    audio = load_audio("test_file.wav")

    # Transcribe
    text = model.stt(audio)
    print(f"Transcription: {text}")

if __name__ == '__main__':
    freeze_support()
    main()