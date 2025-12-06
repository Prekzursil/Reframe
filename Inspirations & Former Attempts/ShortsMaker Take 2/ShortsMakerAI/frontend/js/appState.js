// Application State Management Module

let _originalVideoFilepath = null;
let _selectedClipData = null;
let _currentTaskId = null;
let _lastProgressTimestamp = 0;
let _lastKnownProgressPercent = 0;
let _lastKnownMessage = '';
let _ellipsisIntervalId = null;

export function getOriginalVideoFilepath() { return _originalVideoFilepath; }
export function setOriginalVideoFilepath(path) { _originalVideoFilepath = path; }

export function getSelectedClipData() { return _selectedClipData; }
export function setSelectedClipData(data) { _selectedClipData = data; }

export function getCurrentTaskId() { return _currentTaskId; }
export function setCurrentTaskId(id) { _currentTaskId = id; }

export function getLastProgressTimestamp() { return _lastProgressTimestamp; }
export function setLastProgressTimestamp(ts) { _lastProgressTimestamp = ts; }

export function getLastKnownProgressPercent() { return _lastKnownProgressPercent; }
export function setLastKnownProgressPercent(pct) { _lastKnownProgressPercent = pct; }

export function getLastKnownMessage() { return _lastKnownMessage; }
export function setLastKnownMessage(msg) { _lastKnownMessage = msg; }

export function getEllipsisIntervalId() { return _ellipsisIntervalId; }
export function setEllipsisIntervalId(id) { _ellipsisIntervalId = id; }

export function resetUploadState() {
    // Does not reset originalVideoFilepath as that's set by final_result
    // Does not reset currentTaskId as that's generated per upload by uploadHandler
    setSelectedClipData(null);
    if (getEllipsisIntervalId()) {
        clearInterval(getEllipsisIntervalId());
        setEllipsisIntervalId(null);
    }
    setLastProgressTimestamp(0);
    setLastKnownProgressPercent(0);
    setLastKnownMessage('');
}
