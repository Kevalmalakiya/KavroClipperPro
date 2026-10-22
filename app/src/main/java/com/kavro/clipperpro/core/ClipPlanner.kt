package com.kavro.clipperpro.core

import java.util.Locale

data class ClipRange(val index: Int, val startMs: Long, val endMs: Long) {
    val durationMs: Long get() = endMs - startMs
}

sealed class PlanResult {
    data class Ok(val clips: List<ClipRange>) : PlanResult()
    data class Error(val message: String) : PlanResult()
}

object ClipPlanner {
    const val MAX_CLIP_COUNT = 50
    const val MIN_CLIP_SECONDS = 1
    const val MAX_CLIP_SECONDS = 3600

    /**
     * Sequential clips from the start of the video.
     * Clip i covers [(i-1)*d, i*d). Never generates fewer clips than requested.
     */
    fun plan(videoDurationMs: Long, countInput: String, secondsInput: String): PlanResult {
        val count = countInput.trim().toIntOrNull()
            ?: return PlanResult.Error("Enter the number of clips as a whole number.")
        val seconds = secondsInput.trim().toIntOrNull()
            ?: return PlanResult.Error("Enter the clip duration in whole seconds.")

        if (count !in 1..MAX_CLIP_COUNT) {
            return PlanResult.Error("Number of clips must be between 1 and $MAX_CLIP_COUNT.")
        }
        if (seconds !in MIN_CLIP_SECONDS..MAX_CLIP_SECONDS) {
            return PlanResult.Error(
                "Clip duration must be between $MIN_CLIP_SECONDS and $MAX_CLIP_SECONDS seconds."
            )
        }
        if (videoDurationMs <= 0L) {
            return PlanResult.Error("The video length is unknown.")
        }

        val clipMs = seconds * 1000L
        val neededMs = clipMs * count
        if (neededMs > videoDurationMs) {
            val fitCount = videoDurationMs / clipMs
            val maxSecondsEach = videoDurationMs / 1000L / count
            val hint = when {
                fitCount >= 1 && maxSecondsEach >= 1 ->
                    "Use up to $fitCount clips of $seconds seconds, or up to $maxSecondsEach seconds each for $count clips."
                fitCount >= 1 ->
                    "Use up to $fitCount clips of $seconds seconds."
                else ->
                    "The video is shorter than one $seconds-second clip. Choose a shorter duration."
            }
            return PlanResult.Error(
                "The video is ${formatMs(videoDurationMs)} long, but $count clips of $seconds seconds " +
                    "need ${formatMs(neededMs)}. $hint"
            )
        }

        val clips = (0 until count).map { i ->
            ClipRange(index = i + 1, startMs = i * clipMs, endMs = (i + 1) * clipMs)
        }
        return PlanResult.Ok(clips)
    }

    fun formatMs(ms: Long): String {
        val total = ms / 1000L
        val h = total / 3600L
        val m = (total % 3600L) / 60L
        val s = total % 60L
        return if (h > 0) {
            String.format(Locale.US, "%d:%02d:%02d", h, m, s)
        } else {
            String.format(Locale.US, "%02d:%02d", m, s)
        }
    }
}
