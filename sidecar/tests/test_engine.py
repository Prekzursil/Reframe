"""Contract + coverage test for the engine facade (``media_studio.engine``).

The facade is pure wiring: namespaced ``@dataclass`` singletons (captions-export)
plus flat re-exports (audio-stabilize + system-advanced). Importing it executes
every binding, so these checks both pin the public surface and cover the module.
"""

from __future__ import annotations

from media_studio import engine
from media_studio.features import (
    audiomix,
    caption_polish,
    ctc_align,
    diarize,
    health,
    nle_export,
    offline,
    package_export,
    parakeet_asr,
    pyannote_backend,
    recipes,
    silencetrim,
    stabilize,
    subtitles,
    transcribe,
)


def test_all_names_resolve() -> None:
    assert isinstance(engine.__all__, list)
    assert engine.__all__  # non-empty
    for name in engine.__all__:
        assert hasattr(engine, name), f"engine.__all__ lists missing attr: {name}"


def test_subtitles_namespace_binds_features() -> None:
    assert engine.subtitles.generate is subtitles.generate
    assert engine.subtitles.generate_polished is subtitles.generate_polished
    assert engine.subtitles.edit is subtitles.edit
    assert engine.subtitles.translate is subtitles.translate
    assert engine.subtitles.stack_bilingual is subtitles.stack_bilingual
    assert engine.subtitles.stack_cue_text is subtitles.stack_cue_text
    assert engine.subtitles.serialize is subtitles.serialize
    assert engine.subtitles.export is subtitles.export


def test_nle_namespace_binds_features() -> None:
    assert engine.nle.FPS_CHOICES == nle_export.FPS_CHOICES
    assert engine.nle.FORMATS == nle_export.FORMATS
    assert engine.nle.clips_to_events is nle_export.clips_to_events
    assert engine.nle.build_edl is nle_export.build_edl
    assert engine.nle.build_csv is nle_export.build_csv
    assert engine.nle.seconds_to_timecode is nle_export.seconds_to_timecode
    assert engine.nle.serialize is nle_export.serialize
    assert engine.nle.export is nle_export.export


def test_package_namespace_binds_features() -> None:
    assert engine.package.build_suggestion is package_export.build_suggestion
    assert engine.package.build_manifest is package_export.build_manifest
    assert engine.package.slugify_tags is package_export.slugify_tags
    assert engine.package.package is package_export.package


def test_audio_stabilize_flat_reexports() -> None:
    assert engine.StabilizeEngine is stabilize.StabilizeEngine
    assert engine.StabilizeError is stabilize.StabilizeError
    assert engine.StabilizeService is stabilize.StabilizeService
    assert engine.make_unavailable_notice is stabilize.make_unavailable_notice
    assert engine.stabilize_available is stabilize.vidstab_available
    assert engine.stabilize_clip is stabilize.stabilize_clip
    assert engine.AudioMix is audiomix.AudioMix
    assert engine.AudioMixError is audiomix.AudioMixError
    assert engine.build_audio_mix_argv is audiomix.build_mix_argv
    assert engine.build_audio_mix_filter is audiomix.build_mix_filter
    assert engine.build_loudnorm_argv is audiomix.build_loudnorm_argv
    assert engine.SilenceTrim is silencetrim.SilenceTrim
    assert engine.SilenceTrimError is silencetrim.SilenceTrimError
    assert engine.detect_silence_spans is silencetrim.detect_silence_spans
    assert engine.keep_spans is silencetrim.keep_spans
    assert engine.parse_silence_spans is silencetrim.parse_silence_spans
    assert engine.removed_seconds is silencetrim.removed_seconds
    assert engine.trim_silence is silencetrim.trim_clip


def test_system_advanced_flat_reexports() -> None:
    assert engine.OfflineError is offline.OfflineError
    assert engine.is_offline is offline.is_offline
    assert engine.guard_network is offline.guard_network
    assert engine.enforce_offline_env is offline.enforce_offline_env
    assert engine.SETTING_OFFLINE is offline.SETTING_OFFLINE
    assert engine.Health is health.Health
    assert engine.parse_ffmpeg_version is health.parse_ffmpeg_version
    assert engine.ML_BACKENDS is health.ML_BACKENDS
    assert engine.RecipeStore is recipes.RecipeStore
    assert engine.Recipes is recipes.Recipes
    assert engine.normalize_recipe is recipes.normalize_recipe
    assert engine.resolve_refs is recipes.resolve_refs
    assert engine.Diarize is diarize.Diarize
    assert engine.diarize_transcript is diarize.diarize_transcript
    assert engine.greedy_cluster is diarize.greedy_cluster
    assert engine.cosine_similarity is diarize.cosine_similarity
    assert engine.speaker_label is diarize.speaker_label
    assert engine.DIARIZE_REQUIRED_ASSETS is diarize.REQUIRED_ASSETS


def test_phase8_flat_reexports() -> None:
    # diarize 2nd backend (opt-in pyannote)
    assert engine.PyannoteDiarizer is pyannote_backend.PyannoteDiarizer
    assert engine.select_diarize_backend is pyannote_backend.select_backend_factory
    assert engine.selected_diarize_backend is pyannote_backend.selected_backend_name
    # ASR engine selection (WU7)
    assert engine.transcribe_file is transcribe.transcribe_file
    assert engine.transcribe_with_engine is transcribe.transcribe_with_engine
    assert engine.selected_asr_engine is transcribe.selected_asr_engine
    assert engine.ASR_ENGINES is transcribe.ASR_ENGINES
    assert engine.parakeet_transcribe is parakeet_asr.transcribe_file
    assert engine.ParakeetLoader is parakeet_asr.ParakeetLoader
    # word-timing alignment (WU6)
    assert engine.align_words is ctc_align.align_words
    # caption polish (WU9)
    assert engine.polish_cues is caption_polish.polish_cues
    assert engine.CAPTION_MAX_CPS == caption_polish.MAX_CPS
    assert engine.CAPTION_MAX_CPL == caption_polish.MAX_CPL
