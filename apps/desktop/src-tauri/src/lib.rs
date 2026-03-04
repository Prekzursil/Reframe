use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::{Mutex, OnceLock};

fn find_repo_root() -> Result<PathBuf, String> {
    let mut current = std::env::current_dir().map_err(|e| format!("Unable to read current dir: {e}"))?;
    loop {
        let marker = current.join("apps").join("api").join("app").join("main.py");
        if marker.is_file() {
            return Ok(current);
        }
        if !current.pop() {
            break;
        }
    }
    Err("Could not locate repo root with apps/api/app/main.py; run desktop app from a repository checkout.".to_string())
}

fn format_output(stdout: &[u8], stderr: &[u8]) -> String {
    let mut out = String::new();
    if !stdout.is_empty() {
        out.push_str(&String::from_utf8_lossy(stdout));
    }
    if !stderr.is_empty() {
        if !out.ends_with('\n') && !out.is_empty() {
            out.push('\n');
        }
        out.push_str(&String::from_utf8_lossy(stderr));
    }
    out.trim().to_string()
}

fn run_checked(mut cmd: Command) -> Result<String, String> {
    let output = cmd.output().map_err(|e| format!("Command failed to start: {e}"))?;
    let rendered = format_output(&output.stdout, &output.stderr);
    if output.status.success() {
        return Ok(rendered);
    }
    let code = output
        .status
        .code()
        .map(|c| c.to_string())
        .unwrap_or_else(|| "unknown".to_string());
    Err(format!("Command failed (exit {code})\n{rendered}"))
}

fn candidate_python_binaries(repo_root: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(explicit) = std::env::var("REFRAME_DESKTOP_PYTHON") {
        let trimmed = explicit.trim();
        if !trimmed.is_empty() {
            candidates.push(PathBuf::from(trimmed));
        }
    }

    candidates.push(repo_root.join(".venv").join("Scripts").join("python.exe"));
    candidates.push(repo_root.join(".venv").join("bin").join("python"));
    candidates.push(PathBuf::from("python"));
    candidates.push(PathBuf::from("python3"));

    candidates
}

fn resolve_python_binary(repo_root: &Path) -> Result<PathBuf, String> {
    for candidate in candidate_python_binaries(repo_root) {
        if candidate.is_absolute() {
            if candidate.is_file() {
                return Ok(candidate);
            }
            continue;
        }

        let mut cmd = Command::new(&candidate);
        cmd.arg("--version");
        if cmd.output().is_ok() {
            return Ok(candidate);
        }
    }

    Err("No usable Python runtime found. Install Python 3.11+ or set REFRAME_DESKTOP_PYTHON.".to_string())
}

fn pythonpath_for_repo(repo_root: &Path) -> Result<OsString, String> {
    let paths = vec![
        repo_root.to_path_buf(),
        repo_root.join("apps").join("api"),
        repo_root.join("packages").join("media-core").join("src"),
    ];
    std::env::join_paths(paths).map_err(|e| format!("Unable to assemble PYTHONPATH: {e}"))
}

#[derive(Default)]
struct RuntimeState {
    api: Option<Child>,
}

fn runtime_state() -> &'static Mutex<RuntimeState> {
    static STATE: OnceLock<Mutex<RuntimeState>> = OnceLock::new();
    STATE.get_or_init(|| Mutex::new(RuntimeState::default()))
}

fn api_is_running(state: &mut RuntimeState) -> Result<bool, String> {
    if let Some(child) = state.api.as_mut() {
        match child.try_wait().map_err(|e| format!("Failed to inspect API process: {e}"))? {
            Some(_) => {
                state.api = None;
                Ok(false)
            }
            None => Ok(true),
        }
    } else {
        Ok(false)
    }
}

fn start_local_runtime() -> Result<String, String> {
    let repo_root = find_repo_root()?;
    let python = resolve_python_binary(&repo_root)?;
    let pythonpath = pythonpath_for_repo(&repo_root)?;

    let mut guard = runtime_state().lock().map_err(|_| "Runtime state lock poisoned".to_string())?;
    if api_is_running(&mut guard)? {
        let pid = guard.api.as_ref().map(|c| c.id()).unwrap_or_default();
        return Ok(format!("local runtime already running (api pid {pid})"));
    }

    let mut cmd = Command::new(&python);
    cmd.current_dir(&repo_root)
        .arg("-m")
        .arg("uvicorn")
        .arg("app.main:create_app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg("8000")
        .env("PYTHONPATH", pythonpath)
        .env("REFRAME_LOCAL_QUEUE_MODE", "true")
        .env("REFRAME_BROKER_URL", "memory://")
        .env("REFRAME_RESULT_BACKEND", "cache+memory://")
        .env("REFRAME_API_BASE_URL", "http://localhost:8000")
        .env("REFRAME_APP_BASE_URL", "http://localhost:5173");

    let child = cmd.spawn().map_err(|e| format!("Failed to start local runtime API process: {e}"))?;
    let pid = child.id();
    guard.api = Some(child);
    Ok(format!("local runtime started (api pid {pid})"))
}

fn stop_local_runtime() -> Result<String, String> {
    let mut guard = runtime_state().lock().map_err(|_| "Runtime state lock poisoned".to_string())?;
    if let Some(mut child) = guard.api.take() {
        let pid = child.id();
        child.kill().map_err(|e| format!("Failed to stop local runtime API process {pid}: {e}"))?;
        let _ = child.wait();
        return Ok(format!("local runtime stopped (api pid {pid})"));
    }
    Ok("local runtime is not running".to_string())
}

fn local_runtime_status() -> Result<String, String> {
    let mut guard = runtime_state().lock().map_err(|_| "Runtime state lock poisoned".to_string())?;
    if api_is_running(&mut guard)? {
        let pid = guard.api.as_ref().map(|c| c.id()).unwrap_or_default();
        return Ok(format!("api running (pid {pid})\nqueue mode: local"));
    }
    Ok("api stopped\nqueue mode: local".to_string())
}

#[tauri::command]
fn docker_version() -> Result<String, String> {
    let repo_root = find_repo_root()?;
    let python = resolve_python_binary(&repo_root)?;
    let mut cmd = Command::new(python);
    cmd.arg("--version");
    let version = run_checked(cmd)?;
    Ok(format!("{version}\nmode: local runtime (no docker required)"))
}

#[tauri::command]
fn compose_file_path() -> Result<String, String> {
    Ok(find_repo_root()?.display().to_string())
}

#[tauri::command]
fn compose_ps() -> Result<String, String> {
    local_runtime_status()
}

#[tauri::command]
fn compose_up(build: Option<bool>) -> Result<String, String> {
    let _ = build;
    start_local_runtime()
}

#[tauri::command]
fn compose_down() -> Result<String, String> {
    stop_local_runtime()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            #[cfg(desktop)]
            app.handle()
                .plugin(tauri_plugin_updater::Builder::new().build())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            docker_version,
            compose_file_path,
            compose_ps,
            compose_up,
            compose_down
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
