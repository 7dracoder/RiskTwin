"""Local-only inference adapters for text, vision and speech."""

from dataclasses import dataclass

from packages.config import Settings, get_settings
from packages.inference.base import ModelRef, parse_json_response
from packages.inference.speech import (
    DeterministicSpeechModel,
    OpenAICompatSpeechModel,
    ParakeetMlxSpeechModel,
    SpeechModel,
    Transcript,
    build_speech_model,
)
from packages.inference.text import (
    NullTextModel,
    OllamaTextModel,
    OpenAICompatTextModel,
    TextModel,
    build_text_model,
)
from packages.inference.vision import (
    DeterministicVisionModel,
    OpenAICompatVisionModel,
    VisionModel,
    VisionObservation,
    build_vision_model,
)

__all__ = [
    "DeterministicSpeechModel",
    "DeterministicVisionModel",
    "InferenceSuite",
    "ModelRef",
    "NullTextModel",
    "OllamaTextModel",
    "OpenAICompatSpeechModel",
    "OpenAICompatTextModel",
    "OpenAICompatVisionModel",
    "ParakeetMlxSpeechModel",
    "SpeechModel",
    "TextModel",
    "Transcript",
    "VisionModel",
    "VisionObservation",
    "build_inference_suite",
    "build_speech_model",
    "build_text_model",
    "build_vision_model",
    "parse_json_response",
]


@dataclass(slots=True)
class InferenceSuite:
    text: TextModel
    vision: VisionModel
    speech: SpeechModel

    @property
    def degraded(self) -> bool:
        return any(
            model.info.degraded for model in (self.text, self.vision, self.speech)
        )

    def model_refs(self) -> dict[str, dict[str, object]]:
        return {
            "text": self.text.info.as_dict(),
            "vision": self.vision.info.as_dict(),
            "speech": self.speech.info.as_dict(),
        }

    async def close(self) -> None:
        for model in (self.text, self.vision, self.speech):
            await model.close()


def build_inference_suite(settings: Settings | None = None) -> InferenceSuite:
    settings = settings or get_settings()
    return InferenceSuite(
        text=build_text_model(settings),
        vision=build_vision_model(settings),
        speech=build_speech_model(settings),
    )
