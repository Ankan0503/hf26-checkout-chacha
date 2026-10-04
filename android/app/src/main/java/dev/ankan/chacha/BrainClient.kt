package dev.ankan.chacha

import android.content.Context
import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.URL
import java.util.concurrent.Executors

/** Talks to the brain on your laptop over your home Wi-Fi. Nothing else is ever contacted. */
class BrainClient(private val context: Context) {

    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())

    fun see(body: JSONObject, done: (Result<JSONObject>) -> Unit) =
        call("POST", "/v1/see", body, 60_000, done)

    fun feedback(decision: String, verdict: JSONObject) =
        call("POST", "/v1/feedback", JSONObject().put("decision", decision).put("verdict_id", verdict.optString("id")), 10_000) {}

    fun health(done: (Result<JSONObject>) -> Unit) =
        call("GET", "/v1/health", null, 5_000, done)

    private fun call(method: String, path: String, body: JSONObject?, readTimeout: Int, done: (Result<JSONObject>) -> Unit) {
        val prefs = Prefs(context)
        io.execute {
            val result = runCatching {
                require(prefs.brain.isNotBlank()) { "Open the Checkout Chacha app and enter your laptop's address first." }
                val conn = URL("http://${prefs.brain}$path").openConnection() as HttpURLConnection
                try {
                    conn.requestMethod = method
                    conn.connectTimeout = 4_000
                    conn.readTimeout = readTimeout
                    conn.setRequestProperty("X-Chacha-Token", prefs.code)
                    if (body != null) {
                        conn.doOutput = true
                        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                        conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
                    }
                    val code = conn.responseCode
                    val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                    val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                    when (code) {
                        in 200..299 -> JSONObject(text)
                        401 -> error("Wrong pairing code. Use the code printed on your laptop.")
                        else -> error("Your laptop answered with error $code.")
                    }
                } finally {
                    conn.disconnect()
                }
            }.recoverCatching { e ->
                throw when (e) {
                    is SocketTimeoutException -> IllegalStateException("Your laptop took too long to answer.")
                    is ConnectException, is NoRouteToHostException ->
                        IllegalStateException("Can't reach your laptop at ${prefs.brain}. Same Wi-Fi? Is the brain running?")
                    else -> e
                }
            }
            main.post { done(result) }
        }
    }
}
