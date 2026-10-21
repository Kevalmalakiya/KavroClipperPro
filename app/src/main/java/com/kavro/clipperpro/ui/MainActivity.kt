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
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.MediaController
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.VideoView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.MediaItem
import androidx.media3.common.util.UnstableApi
import androidx.media3.transformer.Composition
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import com.kavro.clipperpro.R
import java.io.File
import java.io.FileInputStream
import java.util.Locale

@androidx.annotation.OptIn(markerClass = [UnstableApi::class])
class MainActivity : AppCompatActivity() {

    private lateinit var btnSelect: Button
    private lateinit var btnClip: Button
    private lateinit var btnCancel: Button
    private lateinit var editStart: EditText
    private lateinit var editEnd: EditText
    private lateinit var txtInfo: TextView
    private lateinit var txtStatus: TextView
    private lateinit var progress: ProgressBar
    private lateinit var videoView: VideoView

    private val handler = Handler(Looper.getMainLooper())
    private var selectedUri: Uri? = null
    private var durationMs: Long = 0L
    private var transformer: Transformer? = null
    private var tempOutput: File? = null

    private val picker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) onVideoSelected(uri)
    }

    private val progressPoller = object : Runnable {
        override fun run() {
            val t = transformer ?: return
            val holder = ProgressHolder()
            if (t.getProgress(holder) != Transformer.PROGRESS_STATE_NOT_STARTED) {
                progress.progress = holder.progress
            }
            handler.postDelayed(this, 300)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        btnSelect = findViewById(R.id.btnSelect)
        btnClip = findViewById(R.id.btnClip)
        btnCancel = findViewById(R.id.btnCancel)
        editStart = findViewById(R.id.editStart)
        editEnd = findViewById(R.id.editEnd)
        txtInfo = findViewById(R.id.txtInfo)
        txtStatus = findViewById(R.id.txtStatus)
        progress = findViewById(R.id.progress)
        videoView = findViewById(R.id.videoView)

        btnSelect.setOnClickListener { picker.launch("video/*") }
        btnClip.setOnClickListener { startClip() }
        btnCancel.setOnClickListener {
            transformer?.cancel()
            tempOutput?.delete()
            finishExport("Cancel kar diya gaya.")
        }
    }

    private fun onVideoSelected(uri: Uri) {
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(this, uri)
            val hasVideo = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_VIDEO)
            val dur = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull() ?: 0L
            if (hasVideo != "yes" || dur <= 0L) {
                txtStatus.text = "Ye file valid video nahi lag rahi."
                return
            }
            selectedUri = uri
            durationMs = dur
            txtInfo.text = "Video length: ${formatMs(dur)}"
            editStart.isEnabled = true
            editEnd.isEnabled = true
            btnClip.isEnabled = true
            editStart.setText("0")
            editEnd.setText(formatMs(minOf(dur, 10_000L)))
            txtStatus.text = "Start aur end time daaliye, phir 'Clip banayein' dabaiye."

            videoView.visibility = View.VISIBLE
            videoView.setMediaController(MediaController(this).also { it.setAnchorView(videoView) })
            videoView.setVideoURI(uri)
            videoView.seekTo(1)
        } catch (e: Exception) {
            txtStatus.text = "Video khol nahi paye: ${e.message}"
        } finally {
            try { retriever.release() } catch (_: Exception) {}
        }
    }

    /** Accepts "90", "90.5", "01:30", "1:02:03". Returns milliseconds or null if invalid. */
    private fun parseTimeMs(text: String): Long? {
        val parts = text.trim().split(":")
        if (parts.isEmpty() || parts.size > 3) return null
        var seconds = 0.0
        for (p in parts) {
            val v = p.trim().toDoubleOrNull() ?: return null
            if (v < 0) return null
            seconds = seconds * 60 + v
        }
        return (seconds * 1000).toLong()
    }

    private fun formatMs(ms: Long): String {
        val totalSec = ms / 1000
        val h = totalSec / 3600
        val m = (totalSec % 3600) / 60
        val s = totalSec % 60
        return if (h > 0) String.format(Locale.US, "%d:%02d:%02d", h, m, s)
        else String.format(Locale.US, "%02d:%02d", m, s)
    }

    private fun startClip() {
        val uri = selectedUri ?: return
        val startMs = parseTimeMs(editStart.text.toString())
        val endMs = parseTimeMs(editEnd.text.toString())
        if (startMs == null || endMs == null) {
            txtStatus.text = "Time galat hai. 00:05 ya 5 jaisa likhiye."
            return
        }
        if (endMs <= startMs) {
            txtStatus.text = "End time, start se bada hona chahiye."
            return
        }
        if (endMs > durationMs) {
            txtStatus.text = "End time video (${formatMs(durationMs)}) se bahar hai."
            return
        }

        val out = File(cacheDir, "clip_${System.currentTimeMillis()}.mp4")
        tempOutput = out

        val mediaItem = MediaItem.Builder()
            .setUri(uri)
            .setClippingConfiguration(
                MediaItem.ClippingConfiguration.Builder()
                    .setStartPositionMs(startMs)
                    .setEndPositionMs(endMs)
                    .build()
            )
            .build()
        val edited = EditedMediaItem.Builder(mediaItem).build()

        val t = Transformer.Builder(this)
            .addListener(object : Transformer.Listener {
                override fun onCompleted(composition: Composition, exportResult: ExportResult) {
                    saveToGallery(out)
                }

                override fun onError(
                    composition: Composition,
                    exportResult: ExportResult,
                    exportException: ExportException
                ) {
                    out.delete()
                    finishExport("Clip fail hua: ${exportException.message}")
                }
            })
            .build()
        transformer = t

        setBusy(true)
        txtStatus.text = "Clip ban raha hai..."
        progress.progress = 0
        try {
            t.start(edited, out.absolutePath)
            handler.post(progressPoller)
        } catch (e: Exception) {
            out.delete()
            finishExport("Export shuru nahi hua: ${e.message}")
        }
    }

    private fun saveToGallery(src: File) {
        txtStatus.text = "Save ho raha hai..."
        Thread {
            val name = "KavroClip_${System.currentTimeMillis()}.mp4"
            val message = try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val values = ContentValues().apply {
                        put(MediaStore.Video.Media.DISPLAY_NAME, name)
                        put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
                        put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/KavroClipperPro")
                    }
                    val dest = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                        ?: throw IllegalStateException("Gallery mein jagah nahi bani")
                    contentResolver.openOutputStream(dest)!!.use { os ->
                        FileInputStream(src).use { it.copyTo(os) }
                    }
                    "Clip save ho gaya: Movies/KavroClipperPro/$name"
                } else {
                    val dir = getExternalFilesDir(Environment.DIRECTORY_MOVIES) ?: filesDir
                    dir.mkdirs()
                    val dest = File(dir, name)
                    src.copyTo(dest, overwrite = true)
                    "Clip save ho gaya: ${dest.absolutePath}"
                }
            } catch (e: Exception) {
                "Save fail hua: ${e.message}"
            } finally {
                src.delete()
            }
            runOnUiThread { finishExport(message) }
        }.start()
    }

    private fun finishExport(message: String) {
        handler.removeCallbacks(progressPoller)
        transformer = null
        setBusy(false)
        txtStatus.text = message
    }

    private fun setBusy(busy: Boolean) {
        btnClip.isEnabled = !busy
        btnSelect.isEnabled = !busy
        editStart.isEnabled = !busy
        editEnd.isEnabled = !busy
        btnCancel.visibility = if (busy) View.VISIBLE else View.GONE
        progress.visibility = if (busy) View.VISIBLE else View.GONE
    }

    override fun onDestroy() {
        handler.removeCallbacks(progressPoller)
        if (isFinishing) {
            transformer?.cancel()
            tempOutput?.delete()
        }
        super.onDestroy()
    }
}
