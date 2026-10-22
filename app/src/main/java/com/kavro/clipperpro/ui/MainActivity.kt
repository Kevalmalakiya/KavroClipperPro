package com.kavro.clipperpro.ui

import android.content.ContentValues
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.util.Log
import android.view.View
import android.widget.EditText
import android.widget.MediaController
import android.widget.TextView
import android.widget.VideoView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.widget.doAfterTextChanged
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import com.google.android.material.button.MaterialButton
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.kavro.clipperpro.R
import com.kavro.clipperpro.core.ClipPlanner
import com.kavro.clipperpro.core.ClipRange
import com.kavro.clipperpro.core.PlanResult
import java.io.File
import java.util.Locale

@androidx.annotation.OptIn(markerClass = [UnstableApi::class])
class MainActivity : AppCompatActivity() {

    private lateinit var btnSelect: MaterialButton
    private lateinit var btnGenerate: MaterialButton
    private lateinit var btnCancel: MaterialButton
    private lateinit var editCount: EditText
    private lateinit var editDuration: EditText
    private lateinit var txtFileName: TextView
    private lateinit var txtFileInfo: TextView
    private lateinit var txtSummary: TextView
    private lateinit var txtStatus: TextView
    private lateinit var progress: LinearProgressIndicator
    private lateinit var videoView: VideoView

    private val handler = Handler(Looper.getMainLooper())
    private var selectedUri: Uri? = null
    private var durationMs: Long = 0L
    private var transformer: Transformer? = null
    private var tempOutput: File? = null

    private var pendingClips: List<ClipRange> = emptyList()
    private var currentIndex = 0
    private val savedLocations = mutableListOf<String>()

    /** Incremented on every start, cancel or destroy, so stale callbacks are ignored. */
    private var jobId = 0

    private val picker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) onVideoSelected(uri)
    }

    private val progressPoller = object : Runnable {
        override fun run() {
            val t = transformer ?: return
            val holder = ProgressHolder()
            if (t.getProgress(holder) != Transformer.PROGRESS_STATE_NOT_STARTED) {
                val total = pendingClips.size.coerceAtLeast(1)
                val overall = (currentIndex * 100 + holder.progress) / total
                progress.setProgressCompat(overall.coerceIn(0, 100), true)
            }
            handler.postDelayed(this, 300)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        btnSelect = findViewById(R.id.btnSelect)
        btnGenerate = findViewById(R.id.btnGenerate)
        btnCancel = findViewById(R.id.btnCancel)
        editCount = findViewById(R.id.editCount)
        editDuration = findViewById(R.id.editDuration)
        txtFileName = findViewById(R.id.txtFileName)
        txtFileInfo = findViewById(R.id.txtFileInfo)
        txtSummary = findViewById(R.id.txtSummary)
        txtStatus = findViewById(R.id.txtStatus)
        progress = findViewById(R.id.progress)
        videoView = findViewById(R.id.videoView)

        btnSelect.setOnClickListener { picker.launch("video/*") }
        btnGenerate.setOnClickListener { startGeneration() }
        btnCancel.setOnClickListener { cancelJob() }
        editCount.doAfterTextChanged { updateSummary() }
        editDuration.doAfterTextChanged { updateSummary() }
        updateSummary()
    }

    private fun onVideoSelected(uri: Uri) {
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(this, uri)
            val hasVideo = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_VIDEO)
            val dur = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L
            if (hasVideo != "yes" || dur <= 0L) {
                txtStatus.text = "This file does not look like a valid video. Please pick another one."
                return
            }
            val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH) ?: "?"
            val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT) ?: "?"

            selectedUri = uri
            durationMs = dur
            txtFileName.text = displayName(uri)
            txtFileInfo.text = "${ClipPlanner.formatMs(dur)} • ${width}x${height} • ${formatSize(uri)}"
            btnSelect.text = "Replace Video"

            editCount.isEnabled = true
            editDuration.isEnabled = true
            btnGenerate.isEnabled = true
            if (editCount.text.isNullOrBlank()) editCount.setText("5")
            if (editDuration.text.isNullOrBlank()) editDuration.setText("30")
            updateSummary()

            videoView.visibility = View.VISIBLE
            videoView.setMediaController(MediaController(this).also { it.setAnchorView(videoView) })
            videoView.setVideoURI(uri)
            videoView.seekTo(1)
            txtStatus.text = "Video loaded. Choose the number of clips and their length."
        } catch (e: Exception) {
            Log.e(TAG, "Could not read video metadata", e)
            txtStatus.text = "This video could not be opened. It may be damaged or unsupported."
        } finally {
            try { retriever.release() } catch (_: Exception) {}
        }
    }

    private fun displayName(uri: Uri): String {
        return try {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            } ?: "Selected video"
        } catch (e: Exception) {
            "Selected video"
        }
    }

    private fun formatSize(uri: Uri): String {
        val bytes: Long? = try {
            contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null
            }
        } catch (e: Exception) {
            null
        }
        return if (bytes == null) "size unknown"
        else String.format(Locale.US, "%.1f MB", bytes / 1_048_576.0)
    }

    private fun updateSummary() {
        val count = editCount.text.toString().trim().toIntOrNull()
        val seconds = editDuration.text.toString().trim().toIntOrNull()
        txtSummary.text = if (count != null && seconds != null && count > 0 && seconds > 0) {
            "$count clips • $seconds seconds each"
        } else {
            "Enter whole numbers to see the summary."
        }
    }

    private fun startGeneration() {
        if (selectedUri == null) {
            txtStatus.text = "Select a video first."
            return
        }
        val result = ClipPlanner.plan(durationMs, editCount.text.toString(), editDuration.text.toString())
        when (result) {
            is PlanResult.Error -> {
                txtStatus.text = result.message
                return
            }
            is PlanResult.Ok -> {
                pendingClips = result.clips
            }
        }

        jobId++
        currentIndex = 0
        savedLocations.clear()
        setBusy(true)
        startClip(jobId)
    }

    private fun startClip(job: Int) {
        val uri = selectedUri ?: return
        val clip = pendingClips[currentIndex]
        val out = File(cacheDir, "clip_${job}_${clip.index}.mp4")
        out.delete()
        tempOutput = out

        val mediaItem = MediaItem.Builder()
            .setUri(uri)
            .setClippingConfiguration(
                MediaItem.ClippingConfiguration.Builder()
                    .setStartPositionMs(clip.startMs)
                    .setEndPositionMs(clip.endMs)
                    .build()
            )
            .build()
        val edited = EditedMediaItem.Builder(mediaItem).build()

        val t = Transformer.Builder(this)
            .addListener(object : Transformer.Listener {
                override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                    if (job != jobId) return
                    transformer = null
                    saveClip(out, clip, job)
                }

                override fun onError(
                    composition: Composition,
                    exportResult: ExportResult,
                    exportException: ExportException
                ) {
                    if (job != jobId) return
                    Log.e(TAG, "Export failed", exportException)
                    out.delete()
                    transformer = null
                    failJob("Clip ${clip.index} could not be created. Try a shorter duration or another video.")
                }
            })
            .build()
        transformer = t

        txtStatus.text = "Creating clip ${clip.index} of ${pendingClips.size}..."
        try {
            t.start(edited, out.absolutePath)
            handler.removeCallbacks(progressPoller)
            handler.post(progressPoller)
        } catch (e: Exception) {
            Log.e(TAG, "Export could not start", e)
            out.delete()
            transformer = null
            failJob("Export could not start on this device.")
        }
    }

    private fun saveClip(src: File, clip: ClipRange, job: Int) {
        txtStatus.text = "Saving clip ${clip.index} of ${pendingClips.size}..."
        Thread {
            val outcome = runCatching { saveToGallery(src, clip.index) }
            src.delete()
            runOnUiThread { onClipSaved(outcome, job) }
        }.start()
    }

    private fun onClipSaved(outcome: Result<String>, job: Int) {
        if (job != jobId) return
        val error = outcome.exceptionOrNull()
        if (error != null) {
            Log.e(TAG, "Save failed", error)
            failJob("Clip ${pendingClips[currentIndex].index} could not be saved. Check free storage and try again.")
            return
        }
        outcome.getOrNull()?.let { savedLocations.add(it) }
        currentIndex++
        if (currentIndex < pendingClips.size) {
            startClip(job)
        } else {
            finishJob()
        }
    }

    /** Returns the folder label where the clip was saved. Throws on any failure. */
    private fun saveToGallery(src: File, index: Int): String {
        if (!src.isFile || src.length() == 0L) {
            throw IllegalStateException("The exported file is empty.")
        }
        val name = "KavroClip_${System.currentTimeMillis()}_$index.mp4"

        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Video.Media.DISPLAY_NAME, name)
                put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/KavroClipperPro")
                put(MediaStore.Video.Media.IS_PENDING, 1)
            }
            val uri = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Could not create a gallery entry.")
            try {
                val os = contentResolver.openOutputStream(uri)
                    ?: throw IllegalStateException("Could not open the gallery file.")
                os.use { out -> src.inputStream().use { it.copyTo(out) } }
                val done = ContentValues().apply { put(MediaStore.Video.Media.IS_PENDING, 0) }
                contentResolver.update(uri, done, null, null)
            } catch (e: Exception) {
                contentResolver.delete(uri, null, null)
                throw e
            }
            "Movies/KavroClipperPro"
        } else {
            val base = getExternalFilesDir(Environment.DIRECTORY_MOVIES) ?: filesDir
            val dir = File(base, "KavroClipperPro")
            dir.mkdirs()
            src.copyTo(File(dir, name), overwrite = true)
            dir.absolutePath
        }
    }

    private fun finishJob() {
        handler.removeCallbacks(progressPoller)
        transformer = null
        setBusy(false)
        progress.setProgressCompat(100, true)
        val location = savedLocations.lastOrNull() ?: "app storage"
        txtStatus.text = "Done. ${savedLocations.size} clip(s) saved to $location."
    }

    private fun failJob(message: String) {
        handler.removeCallbacks(progressPoller)
        try { transformer?.cancel() } catch (_: Exception) {}
        transformer = null
        tempOutput?.delete()
        setBusy(false)
        val note = if (savedLocations.isNotEmpty()) {
            " ${savedLocations.size} clip(s) created before this were kept."
        } else {
            ""
        }
        txtStatus.text = message + note
    }

    private fun cancelJob() {
        jobId++
        handler.removeCallbacks(progressPoller)
        try { transformer?.cancel() } catch (_: Exception) {}
        transformer = null
        tempOutput?.delete()
        setBusy(false)
        txtStatus.text = "Cancelled. Clips already saved are still in your gallery."
    }

    private fun setBusy(busy: Boolean) {
        btnGenerate.isEnabled = !busy
        btnSelect.isEnabled = !busy
        editCount.isEnabled = !busy
        editDuration.isEnabled = !busy
        btnCancel.visibility = if (busy) View.VISIBLE else View.GONE
        progress.visibility = if (busy) View.VISIBLE else View.GONE
        if (busy) progress.setProgressCompat(0, false)
    }

    override fun onDestroy() {
        handler.removeCallbacks(progressPoller)
        if (isFinishing) {
            jobId++
            try { transformer?.cancel() } catch (_: Exception) {}
            tempOutput?.delete()
        }
        super.onDestroy()
    }

    companion object {
        private const val TAG = "KavroClipper"
    }
}
