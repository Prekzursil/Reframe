// API communication functions

// Importing UI update functions that might be called directly from API handlers
// (e.g., on immediate error or for upload progress)
// Alternatively, API functions can return promises and main.js can handle UI updates.
// For now, let's keep UI updates separate as much as possible.
// We'll need to pass UI update callbacks or main.js will handle them.

export function uploadVideoToServer(formData, progressBar, statusUpdater, onUploadSuccess, onUploadError) {
    if (progressBar) {
        progressBar.style.display = 'block';
        progressBar.value = 0;
    }
    if (statusUpdater) statusUpdater('Uploading 0%...', 'orange');

    const xhr = new XMLHttpRequest();
    xhr.open('POST', 'http://localhost:5001/upload', true);

    xhr.upload.onprogress = function(event) {
        if (event.lengthComputable) {
            const percentComplete = Math.round((event.loaded / event.total) * 100);
            if (progressBar) progressBar.value = percentComplete;
            if (statusUpdater) statusUpdater(`Uploading ${percentComplete}%...`, 'orange');
        }
    };

    xhr.onload = function() {
        if (progressBar) progressBar.style.display = 'none';
        if (xhr.status === 202) { // Accepted
            try {
                const initialResponse = JSON.parse(xhr.responseText);
                if (statusUpdater) statusUpdater("Upload complete. Server processing started... (Status via WebSocket)", 'blue');
                if (onUploadSuccess) onUploadSuccess(initialResponse.task_id);
            } catch (e) {
                console.error('Error parsing initial JSON response from /upload:', e, xhr.responseText);
                if (statusUpdater) statusUpdater('Error: Invalid initial response from server.', 'red');
                if (onUploadError) onUploadError('Invalid initial response');
            }
        } else {
            let errorMsg = `Upload Error: ${xhr.statusText || 'Unknown server error.'}`;
            try {
                const result = JSON.parse(xhr.responseText);
                if(result.error) errorMsg = `Upload Error: ${result.error}`;
            } catch (e) { /* use default errorMsg */ }
            if (statusUpdater) statusUpdater(errorMsg, 'red');
            if (onUploadError) onUploadError(errorMsg);
        }
    };

    xhr.onerror = function() {
        if (progressBar) progressBar.style.display = 'none';
        const errorMsg = 'Network Error: Could not connect to server for upload.';
        if (statusUpdater) statusUpdater(errorMsg, 'red');
        console.error('XHR Network Error during upload POST');
        if (onUploadError) onUploadError(errorMsg);
    };
    
    xhr.send(formData);
}


export async function createClipOnServer(payload, statusUpdater, onSuccess, onError) {
    if (statusUpdater) statusUpdater(`Creating clip...`, 'orange');

    try {
        const response = await fetch('http://localhost:5001/create_clip', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        });
        const result = await response.json();

        if (response.ok) {
            if (statusUpdater) statusUpdater('Clip created!', 'green'); // Or clear it
            if (onSuccess) onSuccess(result.subtitled_clip_filename, result.raw_clip_filename, result.subtitle_filename);
        } else {
            const errorMsg = `Error creating clip: ${result.error || 'Unknown server error.'}`;
            if (statusUpdater) statusUpdater(errorMsg, 'red');
            if (onError) onError(errorMsg);
        }
    } catch (error) {
        console.error('Create clip fetch/network error:', error);
        const errorMsg = `Network Error: ${error.message || 'Could not connect to server.'}`;
        if (statusUpdater) statusUpdater(errorMsg, 'red');
        if (onError) onError(errorMsg);
    }
}
