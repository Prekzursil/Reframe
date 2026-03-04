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

static RUNTIME_STATE: OnceLock<Mutex<RuntimeState>> = OnceLock::new();

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
        .arg("--factory")
        .arg("app.main:create_app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg("8000")
        .env("PYTHONPATH", pythonpath)
        .env("REFRAME_LOCAL_QUEUE_MODE", "true")
        .env("BROKER_URL", "memory://")
        .env("RESULT_BACKEND", "cache+memory://")
        .env("REFRAME_API_BASE_URL", "http://localhost:8000")
        .env("REFRAME_APP_BASE_URL", "http://localhost:8000")
        .env("REFRAME_MEDIA_ROOT", media_root);

    if let Some(web_dist) = desktop_web_dist(runtime_root) {
        cmd.env("REFRAME_DESKTOP_WEB_DIST", web_dist);
    }
    cmd
}
fn runtime_state_guard() -> Result<MutexGuard<'static, RuntimeState>, String> {
    RUNTIME_STATE
        .get_or_init(|| Mutex::new(RuntimeState::default()))
        .lock()
        .map_err(|_| "Runtime state lock poisoned".to_string())
}

fn spawn_local_runtime(
    runtime_root: &Path,
    python: &Path,
    pythonpath: OsString,
) -> Result<Child, String> {
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
    let mut guard = runtime_state_guard()?;
    if let Some(mut child) = guard.api.take() {
        let pid = child.id();
        if let Some(status) = child
            .try_wait()
            .map_err(|e| format!("Failed to inspect local runtime API process {pid}: {e}"))?
        {
            return Ok(format!(
                "local runtime already stopped (api pid {pid}, status {status})"
            ));
        }
        child
            .kill()
            .map_err(|e| format!("Failed to stop local runtime API process {pid}: {e}"))?;
        let _ = child.wait();
        return Ok(format!("local runtime stopped (api pid {pid})"));
    }
    Ok("local runtime is not running".to_string())
}
fn local_runtime_status() -> Result<String, String> {
    let mut guard = runtime_state_guard()?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use std::fs;
    use std::path::Path;
    use std::sync::{Mutex, MutexGuard, OnceLock};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn env_lock() -> MutexGuard<'static, ()> {
        static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        match ENV_LOCK.get_or_init(|| Mutex::new(())).lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }

    fn unique_temp_dir(prefix: &str) -> PathBuf {
        let mut dir = if cfg!(target_os = "windows") {
            env::var_os("TEMP")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("C:/reframe-test-tmp"))
        } else {
            env::var_os("TMPDIR")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("/tmp/reframe-test-tmp"))
        };
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("time went backwards")
            .as_nanos();
        dir.push("reframe-desktop-tests");
        dir.push(format!("{prefix}-{now}"));
        fs::create_dir_all(&dir).expect("failed to create temp dir");
        dir
    }

    fn write_file(path: &Path, content: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("failed to create parent dir");
        }
        fs::write(path, content).expect("failed to write file");
    }

    #[test]
    fn has_runtime_layout_checks_expected_tree() {
        let root = unique_temp_dir("reframe-runtime-layout");
        assert!(!has_runtime_layout(&root));

        write_file(&root.join("apps").join("api").join("app").join("main.py"), "pass\n");
        fs::create_dir_all(
            root.join("packages")
                .join("media-core")
                .join("src")
                .join("media_core"),
        )
        .expect("failed to create media_core dir");

        assert!(has_runtime_layout(&root));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn format_output_combines_stdout_and_stderr() {
        let rendered = format_output(b"hello", b"warn");
        assert_eq!(rendered, "hello\nwarn");
        assert_eq!(format_output(b"", b""), "");
    }

    #[test]
    fn candidate_python_binaries_honors_explicit_env() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-python-candidates");
        env::set_var("REFRAME_DESKTOP_PYTHON", "custom-python");
        let candidates = candidate_python_binaries(&root);
        assert_eq!(candidates.first().and_then(|p| p.to_str()), Some("custom-python"));
        env::remove_var("REFRAME_DESKTOP_PYTHON");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn pythonpath_for_runtime_contains_api_and_media_core_paths() {
        let root = unique_temp_dir("reframe-pythonpath");
        let joined = pythonpath_for_runtime(&root).expect("pythonpath assembly failed");
        let paths: Vec<PathBuf> = env::split_paths(&joined).collect();

        assert!(paths.contains(&root));
        assert!(paths.contains(&root.join("apps").join("api")));
        assert!(paths.contains(&root.join("packages").join("media-core").join("src")));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn desktop_web_dist_detects_index_file() {
        let root = unique_temp_dir("reframe-web-dist");
        assert!(desktop_web_dist(&root).is_none());

        let dist = root.join("apps").join("web").join("dist");
        write_file(&dist.join("index.html"), "<html></html>");
        assert_eq!(desktop_web_dist(&root), Some(dist));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn runtime_venv_helpers_resolve_expected_paths() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-venv");
        env::set_var("REFRAME_DESKTOP_APP_DATA", root.join("data"));

        let data = desktop_data_dir(&root).expect("desktop data dir");
        assert!(data.is_dir());

        let venv = venv_dir(&root).expect("venv dir");
        let python = venv_python(&venv);
        let marker = venv.join(".reframe_runtime_ready");
        assert!(!runtime_venv_ready(&python, &marker));

        write_file(&python, "");
        write_file(&marker, "ready\n");
        assert!(runtime_venv_ready(&python, &marker));

        env::remove_var("REFRAME_DESKTOP_APP_DATA");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn build_runtime_command_sets_local_queue_defaults() {
        let root = unique_temp_dir("reframe-runtime-cmd");
        let python = PathBuf::from("python");
        let py_path = pythonpath_for_runtime(&root).expect("pythonpath");
        let media_root = root.join("media");
        fs::create_dir_all(&media_root).expect("media root create");

        let cmd = build_runtime_command(&root, &python, py_path, &media_root);
        let args: Vec<String> = cmd
            .get_args()
            .map(|arg| arg.to_string_lossy().to_string())
            .collect();

        assert!(args.contains(&"--factory".to_string()));
        assert!(args.contains(&"app.main:create_app".to_string()));
        assert!(args.contains(&"--port".to_string()));
        assert!(args.contains(&"8000".to_string()));

        let envs: Vec<(String, String)> = cmd
            .get_envs()
            .filter_map(|(k, v)| Some((k.to_string_lossy().to_string(), v?.to_string_lossy().to_string())))
            .collect();

        let find = |key: &str| envs.iter().find(|(k, _)| k == key).map(|(_, v)| v.clone());
        assert_eq!(find("REFRAME_LOCAL_QUEUE_MODE"), Some("true".to_string()));
        assert_eq!(find("BROKER_URL"), Some("memory://".to_string()));
        assert_eq!(find("RESULT_BACKEND"), Some("cache+memory://".to_string()));
        assert_eq!(find("REFRAME_MEDIA_ROOT"), Some(media_root.to_string_lossy().to_string()));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn local_runtime_status_reports_stopped_when_no_child() {
        let status = local_runtime_status().expect("local runtime status");
        assert!(status.contains("api stopped"));
        assert!(status.contains("queue mode: local"));
    }

    #[test]
    fn runtime_root_from_env_rejects_invalid_layout() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-runtime-root-env");
        env::set_var("REFRAME_DESKTOP_RUNTIME_ROOT", &root);
        assert!(runtime_root_from_env().is_none());

        write_file(&root.join("apps").join("api").join("app").join("main.py"), "pass\n");
        fs::create_dir_all(
            root.join("packages")
                .join("media-core")
                .join("src")
                .join("media_core"),
        )
        .expect("failed to create media_core dir");

        let resolved = runtime_root_from_env();
        assert_eq!(resolved, Some(root.clone()));
        env::remove_var("REFRAME_DESKTOP_RUNTIME_ROOT");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn run_checked_handles_success_and_failure() {
        let ok = if cfg!(target_os = "windows") {
            let mut cmd = Command::new("cmd");
            cmd.args(["/C", "echo ok"]);
            cmd
        } else {
            let mut cmd = Command::new("sh");
            cmd.args(["-c", "echo ok"]);
            cmd
        };
        let output = run_checked(ok).expect("expected command success");
        assert!(output.contains("ok"));

        let bad = if cfg!(target_os = "windows") {
            let mut cmd = Command::new("cmd");
            cmd.args(["/C", "exit 7"]);
            cmd
        } else {
            let mut cmd = Command::new("sh");
            cmd.args(["-c", "exit 7"]);
            cmd
        };
        let err = run_checked(bad).expect_err("expected non-zero command to fail");
        assert!(err.contains("exit"));
    }

    #[test]
    fn runtime_requirement_files_require_both_manifests() {
        let root = unique_temp_dir("reframe-runtime-reqs");
        let missing = runtime_requirement_files(&root).expect_err("missing requirements should fail");
        assert!(missing.contains("requirements.txt"));

        write_file(
            &root.join("apps").join("api").join("requirements.txt"),
            "fastapi==0.0\n",
        );
        let missing_worker = runtime_requirement_files(&root).expect_err("worker requirements should still be missing");
        assert!(missing_worker.contains("services"));

        write_file(
            &root.join("services").join("worker").join("requirements.txt"),
            "celery==0.0\n",
        );
        let both = runtime_requirement_files(&root).expect("both requirement files should be discovered");
        assert!(both.0.is_file());
        assert!(both.1.is_file());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn ensure_media_root_uses_desktop_data_dir() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-media-root");
        env::set_var("REFRAME_DESKTOP_APP_DATA", root.join("data"));
        let media = ensure_media_root(&root).expect("media root creation should succeed");
        assert!(media.is_dir());
        assert!(media.ends_with("media"));
        env::remove_var("REFRAME_DESKTOP_APP_DATA");
        let _ = fs::remove_dir_all(root);
    }
    #[test]
    fn find_repo_root_detects_ancestor_layout() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-find-root");
        write_file(&root.join("apps").join("api").join("app").join("main.py"), "pass\n");
        fs::create_dir_all(
            root.join("packages")
                .join("media-core")
                .join("src")
                .join("media_core"),
        )
        .expect("failed to create media_core dir");

        let nested = root.join("apps").join("api");
        fs::create_dir_all(&nested).expect("nested dir create");

        let previous = env::current_dir().expect("current dir");
        env::set_current_dir(&nested).expect("set current dir");
        let found = find_repo_root().expect("expected repo root from ancestor search");
        assert_eq!(found, root);
        env::set_current_dir(previous).expect("restore current dir");

        let _ = fs::remove_dir_all(found);
    }

    #[test]
    fn find_runtime_root_prefers_explicit_env_layout() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-runtime-env");
        write_file(&root.join("apps").join("api").join("app").join("main.py"), "pass\n");
        fs::create_dir_all(
            root.join("packages")
                .join("media-core")
                .join("src")
                .join("media_core"),
        )
        .expect("failed to create media_core dir");

        env::set_var("REFRAME_DESKTOP_RUNTIME_ROOT", &root);
        let found = find_runtime_root().expect("runtime root from env");
        assert_eq!(found, root);
        env::remove_var("REFRAME_DESKTOP_RUNTIME_ROOT");
        let _ = fs::remove_dir_all(found);
    }

    #[test]
    fn mark_runtime_ready_writes_marker_file() {
        let root = unique_temp_dir("reframe-runtime-marker");
        let marker = root.join("ready.marker");
        mark_runtime_ready(&marker).expect("marker write should succeed");
        let payload = fs::read_to_string(&marker).expect("marker read");
        assert_eq!(payload.trim(), "ready");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn create_runtime_venv_if_missing_respects_existing_python_binary() {
        let root = unique_temp_dir("reframe-existing-venv");
        let venv = root.join("venv");
        let python = venv.join(if cfg!(target_os = "windows") {
            "Scripts/python.exe"
        } else {
            "bin/python"
        });
        write_file(&python, "");

        let host = if cfg!(target_os = "windows") {
            PathBuf::from("cmd")
        } else {
            PathBuf::from("sh")
        };

        create_runtime_venv_if_missing(&host, &venv, &python).expect("existing python should short-circuit");
        assert!(python.is_file());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn api_is_running_clears_finished_child_state() {
        let mut state = RuntimeState::default();
        let child = if cfg!(target_os = "windows") {
            let mut cmd = Command::new("cmd");
            cmd.args(["/C", "exit 0"]);
            cmd.spawn().expect("spawn child")
        } else {
            let mut cmd = Command::new("sh");
            cmd.args(["-c", "exit 0"]);
            cmd.spawn().expect("spawn child")
        };

        state.api = Some(child);

        std::thread::sleep(std::time::Duration::from_millis(50));
        let running = api_is_running(&mut state).expect("api_is_running should succeed");
        assert!(!running);
        assert!(state.api.is_none());
    }

    #[test]
    fn api_is_running_reports_true_for_active_child() {
        let mut state = RuntimeState::default();
        let child = if cfg!(target_os = "windows") {
            let mut cmd = Command::new("cmd");
            cmd.args(["/C", "ping -n 3 127.0.0.1 >NUL"]);
            cmd.spawn().expect("spawn child")
        } else {
            let mut cmd = Command::new("sh");
            cmd.args(["-c", "sleep 1"]);
            cmd.spawn().expect("spawn child")
        };
        state.api = Some(child);

        let running = api_is_running(&mut state).expect("api_is_running should succeed");
        assert!(running);
        let _ = stop_local_runtime();
    }

    #[test]
    fn resolve_host_python_binary_handles_absolute_and_path_failure() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-resolve-python");
        let explicit = root.join("python-explicit");
        write_file(&explicit, "placeholder");

        env::set_var("REFRAME_DESKTOP_PYTHON", &explicit);
        let resolved = resolve_host_python_binary(&root).expect("explicit absolute python path");
        assert_eq!(resolved, explicit);

        env::set_var("REFRAME_DESKTOP_PYTHON", root.join("missing-python"));
        let old_path = env::var("PATH").unwrap_or_default();
        env::set_var("PATH", "");
        let err = resolve_host_python_binary(&root).expect_err("missing python candidates should fail");
        assert!(err.contains("No usable Python runtime found"));
        env::set_var("PATH", old_path);
        env::remove_var("REFRAME_DESKTOP_PYTHON");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn desktop_data_dir_falls_back_when_env_blank() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-desktop-data-fallback");
        env::set_var("REFRAME_DESKTOP_APP_DATA", "   ");
        let data = desktop_data_dir(&root).expect("fallback desktop data dir");
        assert!(data.ends_with(".desktop-runtime"));
        assert!(data.is_dir());
        env::remove_var("REFRAME_DESKTOP_APP_DATA");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn create_runtime_venv_if_missing_returns_spawn_error_for_missing_host_binary() {
        let root = unique_temp_dir("reframe-venv-missing-host");
        let venv = root.join("venv");
        let python = venv_python(&venv);
        let missing_host = root.join("missing-host-python");

        let err = create_runtime_venv_if_missing(&missing_host, &venv, &python)
            .expect_err("missing host python must fail");
        assert!(err.contains("Command failed to start"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn install_runtime_requirements_reports_command_failure() {
        let root = unique_temp_dir("reframe-install-runtime-req-fail");
        let missing_python = root.join("missing-python");
        let req_api = root.join("api-req.txt");
        let req_worker = root.join("worker-req.txt");
        write_file(&req_api, "fastapi\n");
        write_file(&req_worker, "celery\n");

        let err = install_runtime_requirements(&missing_python, &req_api, &req_worker)
            .expect_err("missing python binary should fail pip install");
        assert!(err.contains("Command failed to start"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn command_wrappers_fail_closed_when_runtime_root_missing() {
        let _env_guard = env_lock();
        let root = unique_temp_dir("reframe-command-wrapper-missing-root");
        let previous = env::current_dir().expect("current dir");
        env::set_current_dir(&root).expect("switch to isolated cwd");
        env::set_var("REFRAME_DESKTOP_RUNTIME_ROOT", root.join("missing-runtime"));

        let prep_err = runtime_prepare().expect_err("runtime_prepare must fail without runtime root");
        assert!(prep_err.contains("Could not locate runtime root"));

        let docker_err = docker_version().expect_err("docker_version wrapper must fail without runtime root");
        assert!(docker_err.contains("Could not locate runtime root"));

        let compose_path_err = compose_file_path().expect_err("compose_file_path must fail without runtime root");
        assert!(compose_path_err.contains("Could not locate runtime root"));

        let up_err = compose_up(Some(true)).expect_err("compose_up must fail without runtime root");
        assert!(up_err.contains("Could not locate runtime root"));

        let ps = compose_ps().expect("compose_ps fallback status");
        assert!(ps.contains("queue mode: local"));
        let down = compose_down().expect("compose_down fallback status");
        assert!(down.contains("not running"));

        env::remove_var("REFRAME_DESKTOP_RUNTIME_ROOT");
        env::set_current_dir(previous).expect("restore current dir");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn stop_local_runtime_stops_active_child() {
        let mut guard = runtime_state_guard().expect("runtime lock");
        let child = if cfg!(target_os = "windows") {
            let mut cmd = Command::new("cmd");
            cmd.args(["/C", "ping -n 5 127.0.0.1 >NUL"]);
            cmd.spawn().expect("spawn active child")
        } else {
            let mut cmd = Command::new("sh");
            cmd.args(["-c", "sleep 5"]);
            cmd.spawn().expect("spawn active child")
        };
        guard.api = Some(child);
        drop(guard);

        let out = stop_local_runtime().expect("stop local runtime");
        assert!(out.contains("stopped"));
    }

}


