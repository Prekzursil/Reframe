use std::env;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::{Mutex, MutexGuard, OnceLock};

use tauri::Manager;

fn has_runtime_layout(root: &Path) -> bool {
    root.join("apps")
        .join("api")
        .join("app")
        .join("main.py")
        .is_file()
        && root
            .join("packages")
            .join("media-core")
            .join("src")
            .join("media_core")
            .is_dir()
}

fn runtime_root_from_env() -> Option<PathBuf> {
    let raw = env::var("REFRAME_DESKTOP_RUNTIME_ROOT").ok()?;
    let candidate = PathBuf::from(raw);
    if has_runtime_layout(&candidate) {
        Some(candidate)
    } else {
        None
    }
}

fn find_repo_root() -> Result<PathBuf, String> {
    let mut current = env::current_dir().map_err(|e| format!("Unable to read current dir: {e}"))?;
    loop {
        if has_runtime_layout(&current) {
            return Ok(current);
        }
        if !current.pop() {
            break;
        }
    }
    Err("Could not locate runtime root with apps/api/app/main.py; run desktop app from a repository checkout or package runtime resources.".to_string())
}

fn find_runtime_root() -> Result<PathBuf, String> {
    if let Some(root) = runtime_root_from_env() {
        return Ok(root);
    }
    find_repo_root()
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
    let output = cmd
        .output()
        .map_err(|e| format!("Command failed to start: {e}"))?;
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

fn candidate_python_binaries(runtime_root: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(explicit) = env::var("REFRAME_DESKTOP_PYTHON") {
        let trimmed = explicit.trim();
        if !trimmed.is_empty() {
            candidates.push(PathBuf::from(trimmed));
        }
    }

    candidates.push(
        runtime_root
            .join(".venv")
            .join("Scripts")
            .join("python.exe"),
    );
    candidates.push(runtime_root.join(".venv").join("bin").join("python"));
    candidates.push(PathBuf::from("python"));
    candidates.push(PathBuf::from("python3"));

    candidates
}

fn resolve_host_python_binary(runtime_root: &Path) -> Result<PathBuf, String> {
    for candidate in candidate_python_binaries(runtime_root) {
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

    Err(
        "No usable Python runtime found. Install Python 3.11+ or set REFRAME_DESKTOP_PYTHON."
            .to_string(),
    )
}

fn pythonpath_for_runtime(runtime_root: &Path) -> Result<OsString, String> {
    let paths = vec![
        runtime_root.to_path_buf(),
        runtime_root.join("apps").join("api"),
        runtime_root.join("packages").join("media-core").join("src"),
    ];
    env::join_paths(paths).map_err(|e| format!("Unable to assemble PYTHONPATH: {e}"))
}

fn desktop_data_dir(runtime_root: &Path) -> Result<PathBuf, String> {
    if let Ok(raw) = env::var("REFRAME_DESKTOP_APP_DATA") {
        let value = raw.trim();
        if !value.is_empty() {
            let path = PathBuf::from(value);
            fs::create_dir_all(&path)
                .map_err(|e| format!("Unable to create desktop data dir {path:?}: {e}"))?;
            return Ok(path);
        }
    }

    let fallback = runtime_root.join(".desktop-runtime");
    fs::create_dir_all(&fallback)
        .map_err(|e| format!("Unable to create desktop data dir {fallback:?}: {e}"))?;
    Ok(fallback)
}

fn venv_dir(runtime_root: &Path) -> Result<PathBuf, String> {
    Ok(desktop_data_dir(runtime_root)?.join("venv"))
}

fn venv_python(venv_dir: &Path) -> PathBuf {
    if cfg!(target_os = "windows") {
        venv_dir.join("Scripts").join("python.exe")
    } else {
        venv_dir.join("bin").join("python")
    }
}

fn runtime_requirement_files(runtime_root: &Path) -> Result<(PathBuf, PathBuf), String> {
    let req_api = runtime_root
        .join("apps")
        .join("api")
        .join("requirements.txt");
    let req_worker = runtime_root
        .join("services")
        .join("worker")
        .join("requirements.txt");
    if !req_api.is_file() {
        return Err(format!(
            "Missing runtime requirement file: {}",
            req_api.display()
        ));
    }
    if !req_worker.is_file() {
        return Err(format!(
            "Missing runtime requirement file: {}",
            req_worker.display()
        ));
    }
    Ok((req_api, req_worker))
}

fn create_runtime_venv_if_missing(
    host_python: &Path,
    venv: &Path,
    python: &Path,
) -> Result<(), String> {
    if python.is_file() {
        return Ok(());
    }
    let mut create_cmd = Command::new(host_python);
    create_cmd.arg("-m").arg("venv").arg(venv);
    run_checked(create_cmd)?;
    Ok(())
}

fn install_runtime_requirements(
    python: &Path,
    req_api: &Path,
    req_worker: &Path,
) -> Result<(), String> {
    let mut pip_upgrade = Command::new(python);
    pip_upgrade
        .arg("-m")
        .arg("pip")
        .arg("install")
        .arg("--upgrade")
        .arg("pip");
    run_checked(pip_upgrade)?;

    let mut install = Command::new(python);
    install
        .arg("-m")
        .arg("pip")
        .arg("install")
        .arg("-r")
        .arg(req_api)
        .arg("-r")
        .arg(req_worker)
        .env("PIP_DISABLE_PIP_VERSION_CHECK", "1");
    run_checked(install)?;
    Ok(())
}

fn mark_runtime_ready(marker: &Path) -> Result<(), String> {
    fs::write(marker, "ready\n").map_err(|e| {
        format!(
            "Unable to write runtime readiness marker {}: {e}",
            marker.display()
        )
    })
}

fn runtime_venv_ready(python: &Path, marker: &Path) -> bool {
    python.is_file() && marker.is_file()
}

fn bootstrap_runtime_venv(runtime_root: &Path, python: &Path, marker: &Path) -> Result<(), String> {
    let venv = venv_dir(runtime_root)?;
    let host_python = resolve_host_python_binary(runtime_root)?;
    create_runtime_venv_if_missing(&host_python, &venv, python)?;

    let (req_api, req_worker) = runtime_requirement_files(runtime_root)?;
    install_runtime_requirements(python, &req_api, &req_worker)?;
    mark_runtime_ready(marker)
}

fn ensure_runtime_venv(runtime_root: &Path) -> Result<PathBuf, String> {
    let venv = venv_dir(runtime_root)?;
    let python = venv_python(&venv);
    let marker = venv.join(".reframe_runtime_ready");

    if runtime_venv_ready(&python, &marker) {
        return Ok(python);
    }

    bootstrap_runtime_venv(runtime_root, &python, &marker)?;
    Ok(python)
}

fn desktop_web_dist(runtime_root: &Path) -> Option<PathBuf> {
    let candidate = runtime_root.join("apps").join("web").join("dist");
    if candidate.join("index.html").is_file() {
        Some(candidate)
    } else {
        None
    }
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
        match child
            .try_wait()
            .map_err(|e| format!("Failed to inspect API process: {e}"))?
        {
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

fn prepare_local_runtime() -> Result<String, String> {
    let runtime_root = find_runtime_root()?;
    let python = ensure_runtime_venv(&runtime_root)?;

    let mut verify = Command::new(&python);
    verify.arg("-c").arg("import fastapi,uvicorn");
    run_checked(verify)?;

    Ok(format!(
        "local runtime dependencies ready\nroot: {}\npython: {}",
        runtime_root.display(),
        python.display()
    ))
}

fn running_runtime_pid(guard: &mut RuntimeState) -> Result<Option<u32>, String> {
    if api_is_running(guard)? {
        let pid = guard.api.as_ref().map(|c| c.id()).unwrap_or_default();
        return Ok(Some(pid));
    }
    Ok(None)
}

fn ensure_media_root(runtime_root: &Path) -> Result<PathBuf, String> {
    let app_data = desktop_data_dir(runtime_root)?;
    let media_root = app_data.join("media");
    fs::create_dir_all(&media_root).map_err(|e| {
        format!(
            "Unable to create desktop media root {}: {e}",
            media_root.display()
        )
    })?;
    Ok(media_root)
}

fn build_runtime_command(
    runtime_root: &Path,
    python: &Path,
    pythonpath: OsString,
    media_root: &Path,
) -> Command {
    let mut cmd = Command::new(python);
    cmd.current_dir(runtime_root)
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
        .env("REFRAME_APP_BASE_URL", "http://localhost:8000")
        .env("REFRAME_MEDIA_ROOT", media_root);

    if let Some(web_dist) = desktop_web_dist(runtime_root) {
        cmd.env("REFRAME_DESKTOP_WEB_DIST", web_dist);
    }
    cmd
}

fn runtime_state_guard() -> Result<MutexGuard<'static, RuntimeState>, String> {
    runtime_state()
        .lock()
        .map_err(|_| "Runtime state lock poisoned".to_string())
}

fn spawn_local_runtime(runtime_root: &Path, python: &Path, pythonpath: OsString) -> Result<Child, String> {
    let media_root = ensure_media_root(runtime_root)?;
    let mut cmd = build_runtime_command(runtime_root, python, pythonpath, &media_root);
    cmd.spawn()
        .map_err(|e| format!("Failed to start local runtime API process: {e}"))
}

fn start_local_runtime() -> Result<String, String> {
    let runtime_root = find_runtime_root()?;
    let python = ensure_runtime_venv(&runtime_root)?;
    let pythonpath = pythonpath_for_runtime(&runtime_root)?;

    let mut guard = runtime_state_guard()?;
    if let Some(pid) = running_runtime_pid(&mut guard)? {
        return Ok(format!("local runtime already running (api pid {pid})"));
    }

    let child = spawn_local_runtime(&runtime_root, &python, pythonpath)?;
    let pid = child.id();
    guard.api = Some(child);
    Ok(format!("local runtime started (api pid {pid})"))
}

fn stop_local_runtime() -> Result<String, String> {
    let mut guard = runtime_state()
        .lock()
        .map_err(|_| "Runtime state lock poisoned".to_string())?;
    if let Some(mut child) = guard.api.take() {
        let pid = child.id();
        child
            .kill()
            .map_err(|e| format!("Failed to stop local runtime API process {pid}: {e}"))?;
        let _ = child.wait();
        return Ok(format!("local runtime stopped (api pid {pid})"));
    }
    Ok("local runtime is not running".to_string())
}

fn local_runtime_status() -> Result<String, String> {
    let mut guard = runtime_state()
        .lock()
        .map_err(|_| "Runtime state lock poisoned".to_string())?;
    if api_is_running(&mut guard)? {
        let pid = guard.api.as_ref().map(|c| c.id()).unwrap_or_default();
        return Ok(format!("api running (pid {pid})\nqueue mode: local"));
    }
    Ok("api stopped\nqueue mode: local".to_string())
}

#[tauri::command]
fn runtime_prepare() -> Result<String, String> {
    prepare_local_runtime()
}

#[tauri::command]
fn docker_version() -> Result<String, String> {
    let runtime_root = find_runtime_root()?;
    let python = ensure_runtime_venv(&runtime_root)?;
    let mut cmd = Command::new(python);
    cmd.arg("--version");
    let version = run_checked(cmd)?;
    Ok(format!(
        "{version}\nmode: local runtime (no docker required)"
    ))
}

#[tauri::command]
fn compose_file_path() -> Result<String, String> {
    Ok(find_runtime_root()?.display().to_string())
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

            if let Ok(resource_dir) = app.path().resource_dir() {
                let runtime_root = resource_dir.join("runtime");
                if has_runtime_layout(&runtime_root) {
                    env::set_var("REFRAME_DESKTOP_RUNTIME_ROOT", runtime_root);
                }
            }

            if let Ok(data_dir) = app.path().app_data_dir() {
                let _ = fs::create_dir_all(&data_dir);
                env::set_var("REFRAME_DESKTOP_APP_DATA", data_dir);
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            runtime_prepare,
            docker_version,
            compose_file_path,
            compose_ps,
            compose_up,
            compose_down
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
