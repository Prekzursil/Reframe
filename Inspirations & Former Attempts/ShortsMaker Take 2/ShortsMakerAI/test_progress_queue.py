import os
import sys
import time
import threading
import logging
import eventlet
from eventlet import wsgi
from flask import Flask, jsonify
from flask_socketio import SocketIO

# Configure logging
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask and SocketIO
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Global variables
TASK_STATUSES = {}
progress_update_queue = eventlet.queue.Queue()
_queue_processor_running = False
_last_heartbeat_time = time.time()

def enqueue_progress_update(task_id, sid, pct, msg, step_name=""):
    """Thread-safe function to queue a progress update"""
    try:
        progress_update_queue.put({
            "task_id": task_id,
            "sid": sid,
            "pct": pct,
            "msg": msg,
            "step_name": step_name,
            "timestamp": time.time()
        })
        logger.debug(f"Queued progress update for task {task_id}, step '{step_name}'")
    except Exception as e:
        logger.error(f"Error enqueueing progress update: {e}")

def process_progress_queue():
    """Process queued progress updates in the main eventlet thread"""
    global _last_heartbeat_time
    
    # Process all currently queued updates
    processed = 0
    try:
        current_time = time.time()
        
        # Process all updates currently in the queue
        while not progress_update_queue.empty() and processed < 50:
            try:
                update = progress_update_queue.get_nowait()
                task_id = update.get("task_id")
                sid = update.get("sid")
                pct = update.get("pct")
                msg = update.get("msg")
                step_name = update.get("step_name", "")
                
                # Update the task status
                current = TASK_STATUSES.get(task_id, {})
                if current.get("status") not in {"error", "cancelled", "completed"}:
                    current["status"] = "processing"
                
                TASK_STATUSES[task_id] = {
                    **current,
                    "progress_percent": pct,
                    "message": msg,
                    "step": step_name or current.get("step", ""),
                    "last_update": time.time(),
                    "sid": sid
                }
                
                # Emit via socketio
                socket_payload = {
                    "task_id": task_id,
                    "progress_percent": pct,
                    "message": msg
                }
                if step_name:
                    socket_payload["step"] = step_name
                    
                logger.info(f"Emitting progress update: task={task_id}, step='{step_name}', pct={pct}")
                socketio.emit("progress_update", socket_payload, room=sid)
                
                progress_update_queue.task_done()
                processed += 1
                
            except eventlet.queue.Empty:
                break
            except Exception as e:
                logger.error(f"Error processing progress update: {e}")
                try:
                    progress_update_queue.task_done()
                except:
                    pass
        
        # Emit heartbeat updates for active transcription tasks
        if current_time - _last_heartbeat_time >= 2.0:
            for task_id, status in TASK_STATUSES.items():
                if status.get("status") == "processing" and status.get("step") in ["transcribing_progress_fw", "vad_lang_detect_fw"]:
                    socket_payload = {
                        "task_id": task_id,
                        "progress_percent": status.get("progress_percent", 0),
                        "message": status.get("message", "Processing..."),
                        "step": status.get("step", ""),
                        "is_heartbeat": True
                    }
                    sid = status.get("sid")
                    if sid:
                        try:
                            socketio.emit("progress_update", socket_payload, room=sid)
                            logger.info(f"Emitted heartbeat for task {task_id}, step '{status.get('step', '')}'")
                        except Exception as e:
                            logger.error(f"Error emitting heartbeat: {e}")
            
            _last_heartbeat_time = current_time
    
    except Exception as e:
        logger.error(f"Error in process_progress_queue: {e}")
    
    # Schedule the next execution
    if _queue_processor_running:
        socketio.sleep(0.1)
        eventlet.spawn_after(0.1, process_progress_queue)

def start_queue_processor():
    """Start the background task to process progress updates"""
    global _queue_processor_running
    if not _queue_processor_running:
        _queue_processor_running = True
        eventlet.spawn(process_progress_queue)
        logger.info("Progress update queue processor started")

# API route for starting the test
@app.route('/api/test_progress', methods=['GET'])
def test_progress_api():
    task_id = "test_task_123"
    sid = "test_session_456"
    
    # Start a worker thread that will simulate transcription progress
    threading.Thread(target=simulate_transcription_progress, 
                    args=(task_id, sid), 
                    daemon=True).start()
    
    return jsonify({"status": "started", "task_id": task_id})

def simulate_transcription_progress(task_id, sid):
    """Simulate a transcription process with appropriate progress updates"""
    logger.info(f"Starting simulated transcription for task {task_id}")
    
    # Initialize task status
    TASK_STATUSES[task_id] = {
        "status": "processing",
        "progress_percent": 0,
        "message": "Starting transcription...",
        "step": "",
        "last_update": time.time(),
        "sid": sid
    }
    
    # Step 1-2: Model initialization
    enqueue_progress_update(task_id, sid, 25, "Step 2/4 – Initializing transcription model (large-v3)...", "model_init_fw_start")
    time.sleep(0.5)
    enqueue_progress_update(task_id, sid, 34, "Model 'large-v3' (Compute: 'int8_float16') initialized.", "model_init_fw_done")
    time.sleep(0.5)
    
    # Step 3a: VAD/Language detection - this is where we got stuck before
    enqueue_progress_update(task_id, sid, 35, "Step 3/4 - Analyzing audio structure (VAD, Lang Detect)...", "vad_lang_detect_fw")
    time.sleep(5)  # Simulate VAD processing time
    
    # Step 3b: Transcription progress - this is the part where progress was not shown
    for i in range(36, 75):
        # Calculate a simulated ETA
        remaining = 75 - i
        eta_s = remaining * 0.5
        eta_str = time.strftime('%M:%S', time.gmtime(eta_s))
        
        msg = f"Step 3/4 – Transcribing: {i-35}% (ETA: {eta_str})"
        enqueue_progress_update(task_id, sid, i, msg, "transcribing_progress_fw")
        
        # Slow down to simulate the slow transcription process
        time.sleep(0.5)
    
    # Step 4: Post-processing
    enqueue_progress_update(task_id, sid, 80, "Step 4/4 - Post-processing transcript...", "postprocessing")
    time.sleep(2)
    
    # Complete
    enqueue_progress_update(task_id, sid, 100, "Processing complete!", "completed")
    TASK_STATUSES[task_id]["status"] = "completed"
    
    logger.info(f"Simulated transcription completed for task {task_id}")

# Socket.IO event handlers
@socketio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {socketio.rooms}")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info(f"Client disconnected")

# Main HTML page with test UI
@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Progress Queue Test</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.4/socket.io.min.js"></script>
        <style>
            body { font-family: Arial, sans-serif; margin: 2rem; line-height: 1.6; }
            #progress-container { margin: 1rem 0; padding: 1rem; border: 1px solid #ddd; border-radius: 4px; }
            #whisper-container { background-color: #f8f9fa; padding: 1rem; margin-top: 1rem; }
            progress { width: 100%; height: 20px; }
            button { padding: 0.5rem 1rem; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
            button:hover { background: #0069d9; }
            #log { margin-top: 1rem; padding: 1rem; background: #f8f9fa; max-height: 300px; overflow-y: auto; font-family: monospace; }
        </style>
    </head>
    <body>
        <h1>Progress Queue Test</h1>
        <p>This test simulates the transcription progress updates to verify our queuing system works correctly.</p>
        
        <button id="start-test">Start Transcription Test</button>
        
        <div id="progress-container">
            <h3 id="status-msg">Ready</h3>
            <progress id="progress-bar" value="0" max="100"></progress>
            
            <div id="whisper-container">
                <h4>Whisper Progress (Step 3/4)</h4>
                <p id="whisper-progress">Waiting...</p>
                <p id="whisper-eta"></p>
            </div>
        </div>
        
        <h3>Event Log</h3>
        <div id="log"></div>
        
        <script>
            // Connect to Socket.IO
            const socket = io();
            
            // DOM elements
            const startButton = document.getElementById('start-test');
            const statusMsg = document.getElementById('status-msg');
            const progressBar = document.getElementById('progress-bar');
            const whisperProgress = document.getElementById('whisper-progress');
            const whisperEta = document.getElementById('whisper-eta');
            const logContainer = document.getElementById('log');
            
            // Log function
            function log(message) {
                const entry = document.createElement('div');
                entry.textContent = `${new Date().toISOString().substr(11, 8)} - ${message}`;
                logContainer.appendChild(entry);
                logContainer.scrollTop = logContainer.scrollHeight;
            }
            
            // Start test
            startButton.addEventListener('click', () => {
                fetch('/api/test_progress')
                    .then(response => response.json())
                    .then(data => {
                        log(`Test started. Task ID: ${data.task_id}`);
                        startButton.disabled = true;
                        statusMsg.textContent = "Processing...";
                    })
                    .catch(error => {
                        log(`Error starting test: ${error}`);
                    });
            });
            
            // Socket.IO event handlers
            socket.on('connect', () => {
                log('Connected to server');
            });
            
            socket.on('disconnect', () => {
                log('Disconnected from server');
            });
            
            socket.on('progress_update', (data) => {
                log(`Progress: ${data.progress_percent}%, Message: ${data.message}${data.is_heartbeat ? ' (HEARTBEAT)' : ''}`);
                
                // Update progress bar
                progressBar.value = data.progress_percent;
                statusMsg.textContent = data.message;
                
                // Update whisper progress if applicable
                if (data.step === 'transcribing_progress_fw') {
                    const match = data.message.match(/Transcribing: (\d+)% \(ETA: ([^)]+)\)/);
                    if (match) {
                        whisperProgress.textContent = `Transcription: ${match[1]}%`;
                        whisperEta.textContent = `ETA: ${match[2]}`;
                    } else {
                        whisperProgress.textContent = data.message;
                    }
                } 
                else if (data.step === 'vad_lang_detect_fw') {
                    whisperProgress.textContent = 'Analyzing audio...';
                    whisperEta.textContent = '';
                }
                
                // If completed, re-enable the start button
                if (data.progress_percent === 100) {
                    startButton.disabled = false;
                }
            });
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    # Start progress queue processor
    start_queue_processor()
    
    # Start the Flask-SocketIO server
    logger.info("Starting test server on http://localhost:5001")
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
